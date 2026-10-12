#!/usr/bin/env python3
"""
Incremental test selection tool for Fenix.

Analyzes Python import chains to determine which tests are affected by
changes to specific files. Uses AST parsing for accurate analysis.

Usage:
    python3 bin/test_for.py <file1> [file2 ...]     # Run affected tests
    python3 bin/test_for.py --dry-run <file1> ...    # List tests without running
    python3 bin/test_for.py --all                     # Run all tests
"""

import argparse
import ast
import os
import signal
import sys
from pathlib import Path
from typing import Set, Dict, List, Optional
import subprocess

# 有界运行约定（对齐 bin/run_full_suite.py 的 fix-run-hang-amplification）：
# faulthandler_timeout 让挂起用例先打印各线程栈（定位挂点），子进程硬超时兜底
# 中止（独立进程组 SIGTERM→SIGKILL，孙进程一并中止）——存量死循环挂起可超
# 1 小时，裸跑会让开发者终端被无限期挂住。
FAULTHANDLER_TIMEOUT_SECONDS = 300
SUBPROCESS_TIMEOUT_SECONDS = 3600


def normalize_module_path(file_path: str, project_root: Path) -> Optional[str]:
    """Convert file path to Python module path (relative to project root).

    先按 project_root 归一（resolve 会一并解析符号链接），归一失败（目标不在
    项目内）返回 None 由调用方告警——否则绝对路径/无 core·tests 前缀的路径会
    拼出永不匹配的模块名，静默零命中后以「No tests affected」exit 0 收场。
    """
    # Remove .py extension
    path = Path(file_path)
    if path.suffix == ".py":
        path = path.with_suffix("")

    # Normalize to a path under project_root (absolute or cwd-relative alike)
    try:
        rel = path.resolve().relative_to(project_root)
    except ValueError:
        return None

    # Convert to module path (replace / with .)
    parts = list(rel.parts)

    # 保留 project_root 相对全路径作为模块名。旧实现用 parts.index 剥首个出现的
    # core/tests 段，但顶层 core/…、tests/… 路径的模块名本就以该段开头（截断属
    # no-op），而中段同名目录（如 tests/fixtures/scheduling-showcase/tests/
    # foo.py）会被错误折叠成与 build_import_graph 的 tests.* 键空间不符的模块名
    # （core.foo 等），导入链匹配零命中——故取消截断。
    return ".".join(parts)


def extract_imports_from_file(file_path: str) -> Set[str]:
    """Extract all imports from a Python file using AST."""
    imports = set()

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content, filename=file_path)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
    except OSError as e:
        # rglob 扫描与读取之间目标可能被并发删除、权限受限，或是名为 *.py 的
        # 目录；OSError 族按同样 fail-open 口径告警后返回空 imports，单文件
        # 失败不中断全图构建。
        print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)

    return imports


def build_import_graph(tests_dir: str) -> Dict[str, Set[str]]:
    """Build import graph for all test files."""
    graph = {}

    # 与 pytest 收集口径对齐：rglob 递归覆盖嵌套测试目录（如 tests/v2/），
    # 且只收 test_*.py / *_test.py 命名的文件——conftest/helpers 等非测试模块
    # 不再混入图（pytest 选中它们只会空跑），非测试命名的 .py 也不误入。
    for py_file in sorted(Path(tests_dir).rglob("*.py")):
        if py_file.name.startswith("_"):
            continue
        if not (py_file.name.startswith("test_") or py_file.name.endswith("_test.py")):
            continue

        imports = extract_imports_from_file(str(py_file))
        rel_module = ".".join(py_file.relative_to(Path(tests_dir)).with_suffix("").parts)
        module_path = f"tests.{rel_module}"
        graph[module_path] = imports

    return graph


def find_affected_tests(
    target_module: str, import_graph: Dict[str, Set[str]], max_depth: int = 3
) -> Set[str]:
    """Find tests affected by changes to target module.

    Uses BFS to traverse import chain up to max_depth levels.
    Handles partial matches (e.g., core.pm_engine.dispatch matches core.pm_engine).
    """
    affected = set()
    queue = [(target_module, 0)]
    visited = set()

    while queue:
        module, depth = queue.pop(0)

        if module in visited or depth > max_depth:
            continue

        visited.add(module)

        # Check if any test imports this module (or a parent module)
        for test_module, imports in import_graph.items():
            # Check for exact match or partial match (parent module)
            for imp in imports:
                if module == imp or module.startswith(imp + ".") or imp.startswith(module + "."):
                    affected.add(test_module)
                    # Also check transitive imports
                    if depth < max_depth:
                        queue.append((test_module, depth + 1))
                    break

    return affected


def load_test_map(tests_dir: str) -> Dict[str, str]:
    """Load explicit test mappings from test_map.yaml."""
    map_file = Path(tests_dir) / "test_map.yaml"

    if not map_file.exists():
        return {}

    try:
        # 延迟导入（同 bin/fenix_detect_artifacts.py 口径）：PyYAML 缺失的
        # 环境里 --help/--dry-run 不再以 ImportError traceback 收场，此处
        # ImportError 由下方 except Exception 兜住告警后降级为空映射。
        import yaml

        with open(map_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "explicit" not in data:
            return {}

        # explicit 空段（yaml 解析为 None）或误写为列表时回退空映射，
        # 避免 apply_explicit_mappings 对其调 .items() 抛 AttributeError 崩溃。
        if not isinstance(data["explicit"], dict):
            print(
                "Warning: test_map.yaml 'explicit' is not a mapping; ignoring explicit mappings.",
                file=sys.stderr,
            )
            return {}

        return data["explicit"]
    except Exception as e:
        print(f"Warning: Could not load test_map.yaml: {e}", file=sys.stderr)
        return {}


def apply_explicit_mappings(
    target_files: List[str], explicit_map: Dict[str, str], project_root: Path
) -> Set[str]:
    """Apply explicit test mappings for files without import relationships."""
    affected = set()

    # 键/值非字符串（值如手改 yaml 写成 core/foo.py: 123，键如裸数字 8787: ...
    # 被 safe_load 解析为 int）时打告警跳过——值异常进入 affected 后会在消费处
    # test_path.startswith("tests/") 抛 AttributeError，键异常则在本函数
    # pattern.endswith("/") 处抛 AttributeError，均使工具 traceback 崩溃。
    valid_map: Dict[str, str] = {}
    for pattern, test_file in explicit_map.items():
        if isinstance(pattern, str) and isinstance(test_file, str):
            valid_map[pattern] = test_file
        else:
            print(
                f"Warning: test_map.yaml explicit mapping {pattern!r} -> {test_file!r} "
                "is not a string; ignoring this mapping.",
                file=sys.stderr,
            )
    explicit_map = valid_map

    for target_file in target_files:
        # Normalize path——与 normalize_module_path 同口径（先 resolve 再相对化），
        # 否则传入 ./、绝对路径或含 .. 的目标时 startswith 对 yaml 中
        # core/xxx 形态的 pattern 全部失配，显式映射被静默跳过；
        # 归一失败（目标不在项目内）回退原串，保留旧行为。
        target_path = Path(target_file)
        try:
            target_str = str(target_path.resolve().relative_to(project_root))
        except ValueError:
            target_str = str(target_path)

        for pattern, test_file in explicit_map.items():
            # 按路径边界匹配：仅以 '/' 结尾的 pattern 视为目录前缀（前缀匹配），
            # 其余要求与目标完全相等——避免宽松 pattern（如 core/pm）把
            # core/pm_engine/... 等不相关目标也映射进 affected。
            if pattern.endswith("/") and target_str.startswith(pattern):
                affected.add(test_file)
            elif target_str == pattern:
                affected.add(test_file)

    return affected


def run_bounded(cmd: List[str], cwd, timeout: int = SUBPROCESS_TIMEOUT_SECONDS) -> tuple:
    """有界运行命令，硬超时时中止**整个进程组**（同 bin/run_full_suite.run_command）。

    子进程以独立进程组启动（``start_new_session=True``）：超时先对整组发
    SIGTERM 给短暂优雅窗口，未退出再 SIGKILL 整组——pytest 拉起的孙进程
    （v2 dev server、daemon 集成类测试等）一并中止，不留孤儿继续占端口/内存
    （本仓库已知残留 daemon 占端口会让下一次运行恒失败）。进程已退出
    （ProcessLookupError）等 killpg 失败静默吞掉。输出不经管道、直接透传
    终端，faulthandler 栈仍实时可见。

    返回 ``(returncode, timed_out)``；超时中止时 returncode 为 None。
    """
    # [fenix-ignore:f4847e3ea045] basetemp 无需在此注入：tests/conftest.py 的 autouse 会话夹具已把未指定 --basetemp 的直接 pytest 运行兜底指到项目内 .fenix/pytest-basetemp 并在会话末自清，本工具两条 pytest 路径均必然加载该 conftest，不会落系统 /tmp 默认基址。
    proc = subprocess.Popen(cmd, cwd=str(cwd), start_new_session=True)
    try:
        return proc.wait(timeout=timeout), False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)  # start_new_session=True ⇒ pgid==pid
        except OSError:
            pass  # 进程已退出，无需再中止
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # start_new_session=True ⇒ pgid==pid
            except OSError:
                pass  # 进程组已不存在
        try:
            proc.wait(timeout=10)  # 收割 SIGKILL 后的子进程，不留僵尸
        except subprocess.TimeoutExpired:
            pass
        return None, True


def _build_pytest_cmd(extra: List[str]) -> List[str]:
    """构造有界 pytest 命令（run_tests 与 main --all 两路共用，单源化防漂移）。"""
    return [
        sys.executable,
        "-m",
        "pytest",
        "-v",
        "-o",
        f"faulthandler_timeout={FAULTHANDLER_TIMEOUT_SECONDS}",
    ] + extra


def _print_timeout_hint() -> None:
    """打印硬超时中止提示（run_tests 与 main --all 两路共用，单源化防漂移）。"""
    print(
        f"[test_for] 测试运行超过 {SUBPROCESS_TIMEOUT_SECONDS}s，已中止"
        f"（faulthandler {FAULTHANDLER_TIMEOUT_SECONDS}s 起打印的挂起栈见上方输出）；"
        f"挂起定位请改用: python3 bin/run_full_suite.py"
    )


def run_tests(test_files: List[str], dry_run: bool = False) -> bool:
    """Run the specified test files.

    Bounded run: pytest runs with ``-o faulthandler_timeout`` (dumps thread
    stacks on hangs) and a subprocess hard timeout that kills the whole
    process group (孙进程一并中止，同 ``bin/run_full_suite.py``); on timeout
    a hint points to ``bin/run_full_suite.py`` for hanging-test triage.
    """
    if not test_files:
        print("No tests affected. Consider running full test suite.")
        return True

    if dry_run:
        print("Tests that would be run:")
        for test_file in sorted(test_files):
            print(f"  {test_file}")
        return True

    # Run pytest with selected test files (bounded, 同 run_full_suite 约定)
    cmd = _build_pytest_cmd(test_files)
    print(f"Running: {' '.join(cmd)}")

    returncode, timed_out = run_bounded(
        cmd, Path(__file__).resolve().parent.parent, timeout=SUBPROCESS_TIMEOUT_SECONDS
    )
    if timed_out:
        _print_timeout_hint()
        return False
    return returncode == 0


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # Parse arguments（argparse：未知 -- 开头参数报错退出 2，不再被误当目标文件）
    parser = argparse.ArgumentParser(description="Incremental test selection tool for Fenix.")
    parser.add_argument("files", nargs="*", help="target source files to analyze")
    parser.add_argument(
        "--dry-run", action="store_true", help="list affected tests without running them"
    )
    parser.add_argument("--all", action="store_true", help="run all tests")
    args = parser.parse_args()

    dry_run = args.dry_run
    run_all = args.all
    target_files = list(args.files)

    # Get project root
    project_root = Path(__file__).resolve().parent.parent
    tests_dir = project_root / "tests"

    if run_all:
        if target_files:
            # --all 与位置文件参数同传时本分支只跑全量，文件列表被静默丢弃——
            # 打告警提示，避免使用者误以为两类输入都生效。
            print(
                f"Warning: --all ignores the {len(target_files)} given target "
                "file(s); the full test suite will run instead.",
                file=sys.stderr,
            )
        # 有界运行同 run_tests（同款常量）：faulthandler 先打印挂起栈，硬超时兜底中止
        cmd = _build_pytest_cmd([str(tests_dir)])
        if dry_run:
            # --dry-run 与 --all 组合：对齐 run_tests 的 dry-run 语义，
            # 仅列出将执行的完整命令，不实际起 pytest（避免 3600s 硬超时内的真实副作用）
            print(f"Dry-run: {' '.join(cmd)}")
            sys.exit(0)
        print("Running all tests...")
        returncode, timed_out = run_bounded(
            cmd, project_root, timeout=SUBPROCESS_TIMEOUT_SECONDS
        )
        if timed_out:
            _print_timeout_hint()
            sys.exit(1)
        sys.exit(returncode)

    if not target_files:
        print("Error: No files specified. Use --all to run all tests.")
        sys.exit(1)

    # Build import graph
    print("Analyzing import chains...")
    import_graph = build_import_graph(str(tests_dir))
    if not import_graph:
        # 空图（tests/ 缺失或无测试文件）时提示可能分析失效，
        # 避免与「真无受影响测试」混淆后以 exit 0 静默收场。
        print(
            f"Warning: import graph is empty (no test files indexed from {tests_dir}); "
            "analysis may be broken.",
            file=sys.stderr,
        )

    # Find affected tests
    affected_tests = set()

    for target_file in target_files:
        # Convert to module path
        target_module = normalize_module_path(target_file, project_root)
        if target_module is None:
            # 归一失败（目标不在 project_root 下）：模块名不可信，告警并跳过
            # 导入链分析，不让单目标静默零命中后以「No tests affected」exit 0 收场。
            print(
                f"Warning: target {target_file!r} is not under project root "
                f"{project_root}; skipping import-chain analysis for it.",
                file=sys.stderr,
            )
            continue

        # Find tests through import analysis
        tests = find_affected_tests(target_module, import_graph)
        if not tests:
            # 单目标零命中：增量选测可能漏掉该文件，告警提示（不改变退出码）。
            print(
                f"Warning: no indexed test imports {target_module} "
                f"(from {target_file!r}); incremental selection may have missed it.",
                file=sys.stderr,
            )
        affected_tests.update(tests)

    # Apply explicit mappings
    explicit_map = load_test_map(str(tests_dir))
    explicit_tests = apply_explicit_mappings(target_files, explicit_map, project_root)
    # Convert explicit test paths to module paths for consistency
    for test_path in explicit_tests:
        # Convert "tests/test_foo.py" to "tests.test_foo"
        if test_path.startswith("tests/"):
            # 先剥 .py 后缀再替换分隔符，避免串内 ".py" 片段被全量误删
            tail = str(Path(test_path[6:]).with_suffix(""))
            module_path = "tests." + tail.replace("/", ".")
            affected_tests.add(module_path)
        elif test_path.startswith("tests."):
            affected_tests.add(test_path)
        elif test_path:
            # 非 tests/、tests. 前缀的非空值（如误写成 unit/test_x.py 或绝对
            # 路径）在此既不生效也不告警，配置者会误以为映射已生效而漏测；
            # 空字符串值（docs/ → "" 表示无需测试）维持静默跳过的既有约定
            print(
                f"Warning: test_map.yaml explicit mapping value {test_path!r} is "
                "not under tests/ (nor a tests. module path); ignoring it.",
                file=sys.stderr,
            )

    # Convert module paths to file paths
    test_files = []
    for test_module in affected_tests:
        if test_module.startswith("tests."):
            # 模块段的 '.' 全部来自路径分隔符拼接（见 build_import_graph），
            # 回转时须还原为 '/'，否则嵌套测试目录（如
            # tests/fixtures/scheduling-showcase/tests/）的测试被折叠成
            # 不存在的单段路径而被静默丢弃。
            test_file = tests_dir / Path(*test_module[6:].split(".")).with_suffix(".py")
            if test_file.exists():
                test_files.append(str(test_file))
            else:
                # 选中项回转后文件不存在：告警避免静默漏测后给出虚假绿色结论。
                print(
                    f"Warning: selected test {test_module!r} maps to missing file "
                    f"{test_file}; it will not run.",
                    file=sys.stderr,
                )

    # Run tests
    success = run_tests(test_files, dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

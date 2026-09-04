"""
状态文件布局契约（.fenix/ 迁移）——钉住生产代码的默认路径构造。

七个框架状态文件（STATE.md / PROJECT_LOG.md / todo.md / verify.yaml /
config.template.yaml / .STATE.md.lock / .fenix-run-result.json）从项目根
迁入 .fenix/。本文件两层防御：

1. 行为测试：对生产「默认构造点」做功能断言——registry 项目发现、
   dashboard parse_state、verify_report 结果文件回退、engine 项目日志追加。
   （.fenix-run-result.json 的其余回退点由 test_pm_verification /
   test_pm_dispatch / test_verify_report_gate 等既有测试的夹具迁移覆盖。）
2. 静态守卫（AST）：扫描 core/、bin/、fenixd.py，路径拼接链中出现
   "STATE.md" / "PROJECT_LOG.md" / "todo.md" 而链上无 ".fenix" 段即失败——
   防写入端/读取端单侧漂移复发（同 tasks.md 分组格式漂移的防线思路）。

   守卫范围说明：".fenix-run-result.json" 不纳入静态守卫——它的合法形态
   有三（worktree 根 / verify-progress 目录 / 主树 .fenix/），前两者的
   拼接链上没有 ".fenix" 字面段（wt_path / ".fenix-run-result.json"），
   行级无法区分；由上述行为测试钉住。
"""
import ast
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parent.parent

# 静态守卫覆盖的生产 Python 文件
GUARD_TARGETS = (
    [REPO_ROOT / "fenixd.py"]
    + sorted((REPO_ROOT / "bin").glob("*.py"))
    + sorted(p for p in (REPO_ROOT / "core").rglob("*.py"))
)

# 根目录形态即非法的文件名（见模块 docstring 的范围说明）
GUARDED_NAMES = ("STATE.md", "PROJECT_LOG.md", "todo.md")


def _write_fenix_state(root: Path, body: str = "# Fenix Project State\n## Specs\n\n") -> Path:
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    state = root / ".fenix" / "STATE.md"
    state.write_text(body, encoding="utf-8")
    return state


class TestRegistryDiscoveryContract(unittest.TestCase):
    """dashboard 项目发现契约：以 .fenix/STATE.md 为唯一项目标志。"""

    def setUp(self):
        from core.dashboard.registry import Registry
        self.tmpdir = Path(tempfile.mkdtemp())
        self.scan_root = self.tmpdir / "scan"
        self.scan_root.mkdir()
        self.registry = Registry(self.tmpdir / "dashboard.yaml")
        self.registry.save({
            "port": 8787,
            "projects": [],
            "scan_dirs": [str(self.scan_root)],
            "ignored": [],
        })

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_discovers_project_via_fenix_state_md(self):
        proj = self.scan_root / "proj-a"
        _write_fenix_state(proj)
        found = {p["name"] for p in self.registry.discover()}
        self.assertIn("proj-a", found)

    def test_legacy_root_state_md_alone_is_not_a_project(self):
        proj = self.scan_root / "proj-legacy"
        proj.mkdir()
        (proj / "STATE.md").write_text("# Fenix Project State\n## Specs\n\n", encoding="utf-8")
        found = {p["name"] for p in self.registry.discover()}
        self.assertNotIn("proj-legacy", found)

    def test_add_project_requires_fenix_state_md(self):
        proj = self.tmpdir / "proj-b"
        _write_fenix_state(proj)
        ok, _msg = self.registry.add_project(str(proj))
        self.assertTrue(ok)

        legacy = self.tmpdir / "proj-c"
        legacy.mkdir()
        (legacy / "STATE.md").write_text("# state\n## Specs\n\n", encoding="utf-8")
        ok2, msg2 = self.registry.add_project(str(legacy))
        self.assertFalse(ok2)


class TestParseStateReadsFenixLayout(unittest.TestCase):
    """dashboard parse_state：默认构造点必须读 .fenix/STATE.md。"""

    def setUp(self):
        from core.state_machine import StateMachine
        self.tmpdir = Path(tempfile.mkdtemp())
        self.sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", None)
        self.sm.add_spec("demo-spec", {"status": "ready"})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_parse_state_finds_specs_written_under_fenix(self):
        from core.dashboard.data import parse_state
        parsed = parse_state(self.tmpdir)
        self.assertIn("demo-spec", parsed)


class TestEngineProjectLogInFenix(unittest.TestCase):
    """PMEngine 项目日志：默认追加目标必须是 .fenix/PROJECT_LOG.md。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine
        self.tmpdir = Path(tempfile.mkdtemp())
        sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", None)
        self.engine = PMEngine(sm, None, {}, self.tmpdir, None)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_append_project_log_writes_into_fenix(self):
        self.engine._append_project_log("布局契约冒烟")
        log_file = self.tmpdir / ".fenix" / "PROJECT_LOG.md"
        self.assertTrue(log_file.exists())
        self.assertIn("布局契约冒烟", log_file.read_text(encoding="utf-8"))


class TestVerifyReportRunResultFallback(unittest.TestCase):
    """verify_report 结果回退：主树回退点必须是 .fenix/.fenix-run-result.json。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fallback_reads_shared_result_from_fenix(self):
        from core.verify_report import _load_run_result
        (self.tmpdir / ".fenix").mkdir()
        (self.tmpdir / ".fenix" / ".fenix-run-result.json").write_text(
            '{"status": "success", "spec": "spec-x"}', encoding="utf-8")
        data = _load_run_result(self.tmpdir, "spec-x")
        self.assertIsNotNone(data)
        self.assertEqual(data.get("spec"), "spec-x")


class TestNoLegacyRootConstruction(unittest.TestCase):
    """AST 静态守卫：生产代码禁止根目录形态的状态文件拼接（见模块 docstring）。"""

    def _path_chain_strings(self, node):
        """收集 / 拼接链上的全部字符串常量（a / "b" / "c" → [a?, b, c]）。"""
        parts, stack = [], [node]
        while stack:
            n = stack.pop()
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
                stack.extend([n.left, n.right])
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                parts.append(n.value)
        return parts

    def test_production_code_has_no_legacy_root_construction(self):
        offenders = []
        for py in GUARD_TARGETS:
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
                    continue
                parts = self._path_chain_strings(node)
                if ".fenix" in parts:
                    continue
                for name in GUARDED_NAMES:
                    if name in parts:
                        offenders.append(
                            f"{py.relative_to(REPO_ROOT)}:{node.lineno}: "
                            f"根目录形态拼接 /{name!r}")
        self.assertEqual(offenders, [], "生产代码出现根目录状态文件构造:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()

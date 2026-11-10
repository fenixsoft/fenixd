"""add-platform-abstraction-layer 6.1：PAL 守卫——业务代码 POSIX 面与平台判断面防漂移。

两组静态断言（AST 口径：调用/导入语法与字符串字面量；注释与 docstring 词面
天然不在 AST 里，不命中）：

- ① POSIX 面：core/（唯一豁免 ``core/platform/linux.py``）零 ``import fcntl``、
  ``from fcntl import``、``import pwd``、``os.killpg(``、``from os import
  killpg``、``os.setsid(``、``start_new_session=``、``prctl``、``/proc/``。
  ``/proc/`` 按裸字面量口径断言字符串常量（含 f-string 常量段、排除
  docstring）——任务书实测：存量 16 个命中文件中 6 个为单引号/f-string 形态，
  双引号前缀 grep 口径仅命中 10 个、会漏检回潮。systemd_hosting 两处渲染
  payload（unit 注释行 + environ 捕获失败错误文案，渲染逐字段一致是验收
  约束）按文件级豁免登记并双向钉计数防漂移。

- ② 平台判断面：core/（豁免整个 ``core/platform/``，``__init__.py`` 的
  sys.platform 单点分发为设计内唯一分支点）零 ``sys.platform`` /
  ``platform.system`` / ``os.name`` 属性访问（spec Requirement 1「业务代码
  零平台分支」场景的守卫执行面；平台判定唯一合法替身是 ``pal.IS_WINDOWS``）。
"""

import ast
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent.parent / "core"

# ① 组整文件豁免（唯一）：pal Linux 后端本体——fcntl/pwd 导入、os.killpg/
# os.setsid 调用、start_new_session 关键字、prctl、procfs 路径常量的全库
# 唯一位点（数量面由 test_killpg_self_guard 的 _GUARD_MODULE_SITES 另行钉死）。
POSIX_EXEMPT_FILES = {"core/platform/linux.py"}

# ① 组 /proc/ 字符串面的文件级豁免（值＝该文件内含 "/proc/" 的非 docstring
# 字符串常量数量，断言双向钉死：回潮或消失都判漂移）——systemd unit 注释行
# payload + environ 捕获失败错误文案，渲染逐字段一致是 SPEC 验收约束。
PROCFS_PAYLOAD_EXEMPT = {"core/systemd_hosting.py": 2}

# ① 组 start_new_session 关键字的位点级豁免（值＝该文件内 keyword 出现数，
# 断言双向钉死：回潮或消失都判漂移）——runner.py _run_agent spawn 位点是
# 测试缝 shadow 转发本身：start_new_session 键为主树 Popen 形态契约保留
# （test_harness_claude_snapshot golden 快照桩按主树键集逐位断言），实际经
# 模块级 _popen_via_pal 翻译为 pal.spawn_detached 单源 new_session——独立
# 进程组纪律仍收 pal，本豁免不构成 syscall 绕行通道。
START_NEW_SESSION_KEYWORD_EXEMPT = {"core/agent_runner/runner.py": 1}


def _iter_core_files():
    for path in sorted(CORE_DIR.rglob("*.py")):
        yield path.relative_to(CORE_DIR.parent).as_posix(), path


def _parse_module(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _docstring_node_ids(tree):
    """模块/类/函数首语句 docstring 的 Constant 节点 id 集（/proc/ 面排除用）。"""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _module_aliases(tree):
    """{绑定名: 顶层模块名}——``import os`` → ``{"os": "os"}``、
    ``import os as o`` → ``{"o": "os"}``、``import os.path`` → ``{"os": "os"}``。
    属性访问基座经此映射还原真身，封 ``import os as o; o.killpg(...)`` 与
    ``import sys as s; s.platform`` 别名逃逸。"""
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name.split(".")[0]
    return aliases


def _start_new_session_keyword_hits():
    """① 组 start_new_session 关键字出现位点（豁免钉计数的数据源）。"""
    hits = []
    for rel, path in _iter_core_files():
        if rel in POSIX_EXEMPT_FILES:
            continue
        tree = _parse_module(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "start_new_session":
                        hits.append((rel, node.lineno))
    return hits


def _posix_syntax_violations():
    """① 组语法词面：fcntl/pwd 导入、killpg/setsid 调用与 from os import、
    start_new_session 关键字、prctl 引用（Attribute/Name 两形态）。"""
    violations = []
    for rel, path in _iter_core_files():
        if rel in POSIX_EXEMPT_FILES:
            continue
        tree = _parse_module(path)
        aliases = _module_aliases(tree)
        for node in ast.walk(tree):
            lineno = getattr(node, "lineno", 0)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in ("fcntl", "pwd"):
                        violations.append(f"{rel}:{lineno}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                names = ", ".join(a.name for a in node.names)
                if mod.split(".")[0] in ("fcntl", "pwd"):
                    violations.append(f"{rel}:{lineno}: from {mod} import {names}")
                elif mod == "os" and any(
                    a.name in ("killpg", "setsid") for a in node.names
                ):
                    violations.append(f"{rel}:{lineno}: from os import {names}")
            elif isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and aliases.get(func.value.id, func.value.id) == "os"
                    and func.attr in ("killpg", "setsid")
                ):
                    violations.append(
                        f"{rel}:{lineno}: {func.value.id}.{func.attr}() 直调"
                    )
            elif isinstance(node, ast.Attribute) and node.attr == "prctl":
                violations.append(f"{rel}:{lineno}: prctl 属性访问")
            elif isinstance(node, ast.Name) and node.id == "prctl":
                violations.append(f"{rel}:{lineno}: prctl 名字引用")
    # start_new_session 关键字经位点级豁免钉计数过滤（计数不匹配即报——
    # runner.py shadow 转发缝之外回潮任何一处都不可静默）。
    sns_hits = _start_new_session_keyword_hits()
    sns_counts = {}
    for rel, _ in sns_hits:
        sns_counts[rel] = sns_counts.get(rel, 0) + 1
    for rel, lineno in sns_hits:
        if sns_counts[rel] != START_NEW_SESSION_KEYWORD_EXEMPT.get(rel):
            violations.append(f"{rel}:{lineno}: start_new_session= 关键字")
    return violations


def _procfs_string_hits():
    """全 core/ 非 docstring 含 "/proc/" 的字符串常量：{rel: [(lineno, repr)]}。

    ast.walk 覆盖 f-string（JoinedStr）内的 Constant 常量段——单引号/f-string
    形态的回潮同罪（双引号前缀 grep 口径漏检面的补齐）。
    """
    hits = {}
    for rel, path in _iter_core_files():
        if rel in POSIX_EXEMPT_FILES:
            continue  # linux.py 唯一位点：① 组整文件豁免
        tree = _parse_module(path)
        ds = _docstring_node_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in ds
                and "/proc/" in node.value
            ):
                hits.setdefault(rel, []).append(
                    (node.lineno, node.value[:60])
                )
    return hits


def _platform_branch_violations():
    """② 组：core/platform/ 外零 sys.platform / platform.system / os.name
    属性访问（基座经 import 别名映射还原真身封 ``import sys as s`` 逃逸；
    裸 Name 基座才计数——``foo.platform.system`` 链式不误伤）+ from-import
    直引名禁面（``from sys import platform`` 后裸 Name 使用 AST 不可判，
    禁导入词面本身）。"""
    violations = []
    judged = {("sys", "platform"), ("platform", "system"), ("os", "name")}
    direct_import = {("sys", "platform"), ("platform", "system"), ("os", "name")}
    for rel, path in _iter_core_files():
        if rel.startswith("core/platform/"):
            continue
        tree = _parse_module(path)
        aliases = _module_aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                for a in node.names:
                    if (mod, a.name) in direct_import:
                        violations.append(
                            f"{rel}:{node.lineno}: from {mod} import {a.name}"
                        )
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                base = aliases.get(node.value.id, node.value.id)
                attr = node.attr
                if (base, attr) in judged:
                    violations.append(f"{rel}:{node.lineno}: {base}.{attr} 平台判断")
    return violations


class TestPosixFaceBusinessClean:
    def test_no_posix_syntax_faces_outside_pal_linux(self):
        """fcntl/pwd 导入、killpg/setsid 直调（含 from os import 形态）、
        start_new_session 关键字、prctl 引用在 core/（唯一豁免 linux.py 外）
        零存在——回潮即违「平台 syscall 单点」架构约束。start_new_session
        经位点级豁免（runner.py shadow 转发缝的 Popen 形态契约保留），计数
        双向钉死：回潮或消失都须人工核对同步。"""
        drifted = {
            rel: sum(1 for r, _ in _start_new_session_keyword_hits()
                     if r == rel)
            for rel in START_NEW_SESSION_KEYWORD_EXEMPT
        }
        assert drifted == START_NEW_SESSION_KEYWORD_EXEMPT, (
            f"start_new_session 豁免计数漂移（回潮或消失都须人工核对同步）："
            f"{drifted} != {START_NEW_SESSION_KEYWORD_EXEMPT}"
        )
        violations = _posix_syntax_violations()
        assert not violations, (
            "core/ 出现 POSIX 专属词面（须收敛到 core.platform.linux / pal）：\n"
            + "\n".join(violations)
        )

    def test_procfs_string_constants_zero_with_pinned_exempt(self):
        """/proc/ 字符串常量零回潮；豁免文件计数双向钉死（漂移即人工核对）。"""
        hits = _procfs_string_hits()
        drifted = {
            rel: len(hits.get(rel, [])) for rel in PROCFS_PAYLOAD_EXEMPT
        }
        assert drifted == PROCFS_PAYLOAD_EXEMPT, (
            f"procfs payload 豁免计数漂移（回潮或消失都须人工核对同步）：{drifted} "
            f"!= {PROCFS_PAYLOAD_EXEMPT}"
        )
        violations = [
            f"{rel}:{lineno}: {snippet!r}"
            for rel, found in hits.items()
            if rel not in PROCFS_PAYLOAD_EXEMPT
            for lineno, snippet in found
        ]
        assert not violations, (
            "core/ 出现 \"/proc/\" 字符串常量（须改走 pal B 组原语 / "
            "PROCFS_ROOT 常量化；渲染 payload 须登记 PROCFS_PAYLOAD_EXEMPT）：\n"
            + "\n".join(violations)
        )


class TestPlatformBranchFaceBusinessClean:
    def test_no_platform_judgments_outside_pal(self):
        """core/（豁免整个 core/platform/）零 sys.platform / platform.system /
        os.name 属性访问——平台判定唯一合法替身 pal.IS_WINDOWS（4.3 已清零，
        本断言防回潮）。"""
        violations = _platform_branch_violations()
        assert not violations, (
            "core/ 业务代码出现平台判断（须改 pal.IS_WINDOWS；core/platform/ "
            "__init__.py 单点分发是设计内唯一分支点）：\n" + "\n".join(violations)
        )

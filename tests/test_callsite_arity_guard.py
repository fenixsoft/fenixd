"""
callsite-arity-guard — 生产调用点实参数量静态守卫（add-control-plane-silent-failure-guards 防线一）。

AST 扫描 core/**/*.py（排除 node_modules vendored 代码）与 fenixd.py 的
生产调用点：凡 `<obj>.<method>(...)` / `self.<method>(...)` 的**实参必填位
不足**（调用提供的位置参数个数 + 关键字补足 < 该方法唯一签名的最小必填数，
且非 *args/**kwargs 展开）即失败。

事故背景（proposal.md §Why）：`_reset_env_blocked_after_disposition` 调用
`handle_event("spec_implemented", spec)` 而生产签名要求 3 必填位参——
必然 TypeError，自引入起从未成功执行。运行时断言抓不到「调用点写错」（只
会在真跑到那一步才炸），AST 静态扫描不依赖被测代码被执行。

判定规则（design D1/D2，保守起步）：
- 仅当方法名在 core/ 中**唯一签名**（同名多签名 → 排除）、且该签名不含
  *args/**kwargs 时才判定。
- `ast.Starred`（*args 展开）与 `keyword.arg is None`（**kwargs 展开）调用
  不判定（实参数量静态不可知）。
- 关键字补足：关键字名命中该签名位参名时计入已提供。
- 误报白名单：最小粒度 `(相对路径, 方法名, 接收者表达式)`（语义键，不含行号）。
"""

import ast
import tempfile
import unittest
from pathlib import Path

from fenix_guards import (
    VENDORED_DIR_MARKERS,
    index_method_signatures,
    is_vendored,
    parse_tree,
    repo_relative,
    seam_param_names,
    unique_seams,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _core_files() -> list:
    return [
        f for f in sorted((REPO_ROOT / "core").rglob("*.py"))
        if not is_vendored(f)
    ]


def _prod_files() -> list:
    return _core_files() + [REPO_ROOT / "fenixd.py"]


def _rel(path: Path) -> str:
    """仓库相对路径（白名单键用）；仓库外文件（单元测试临时样例）回退绝对路径。"""
    return repo_relative(path, REPO_ROOT)


# ── 误报白名单 ─────────────────────────────────────────────────────────
# 最小粒度 `(相对路径, 方法名, 接收者表达式)` 豁免确有其事的同名误报。
# 语义键**不含行号**——2026-09-15 回归：以行号为键时 core/evolution.py 于
# 文件前部插入 39 行（clear_todo 等）后 SPEC_YAML_TEMPLATE.format 由 803
# 漂到 842，豁免失配 → 守卫误报红灯。核验接收者仍保证「非文件级/全局通配」：
# 只有该文件的该接收者的该调用被豁免，同文件别处的同名调用仍判定。
# 实测当前 core/ + fenixd.py 仅四族：
# 1. core/evolution.py `SPEC_YAML_TEMPLATE.format(...)` 是 str.format（关键字
#    展开），与 core/logger.py 的 Formatter.format(self, record) 同名——
#    string 方法签名不匹配 Formatter 契约，属真实误报。
# 2. Playwright 的 `page.screenshot(path=..., full_page=...)`（0 位参，
#    全关键字）与 core/verify_engine/browser.py 自家
#    screenshot(self, page, name, output_dir) 同名——Playwright API 在
#    core 之外无签名可考，不能按 3 必填位参判定，逐接收者豁免。
# 3. 标准库 logging 的 `logger.exception("单参消息")`（logging.getLogger 返回
#    的 Logger 支持 *args）与 core/logger.py 自研 Logger.exception(component,
#    message, context=None) 同名异签名——core/logger.py 的 exception 成为
#    唯一签名后（item df6de36313c9），三处 stdlib logger 单参调用被误按
#    双必填契约判定，逐文件豁免（接收者均为 `logger`）。
ARITY_WHITELIST = [
    ("core/evolution.py", "format", "SPEC_YAML_TEMPLATE"),
    ("core/verify_engine/browser.py", "screenshot", "page"),
    ("core/verify_engine/visual_diff.py", "screenshot", "page"),
    ("core/dashboard/routes/base.py", "exception", "logger"),
    ("core/dashboard/session_manager.py", "exception", "logger"),
    ("core/worktree_manager/artifact_paths.py", "exception", "logger"),
    # 4. str.format 模板调用（core/pm_engine/dispatch/backoff.py 的
    #    scheduled_log.format(spec_name=..., delay=...)，带 {spec_name}/
    #    {delay} 占位）与 Formatter.format(self, record) 同名异签名——
    #    同族 1 的 str.format 误报（05323eed 引入调用点时漏补豁免）。
    ("core/pm_engine/dispatch/backoff.py", "format", "scheduled_log"),
    # 5. core/agent_runner/maintenance_runs.py 核销守卫公共判定的模板实参
    #    locked_detail_tmpl/unlock_detail_tmpl 是 str.format（全关键字展开，
    #    {cov}/{total} 占位）与 Formatter.format(self, record) 同名异签名——
    #    同族 1/4 的 str.format 误报（item a5262dd130c0 引入调用点时漏补豁免）。
    ("core/agent_runner/maintenance_runs.py", "format", "locked_detail_tmpl"),
    ("core/agent_runner/maintenance_runs.py", "format", "unlock_detail_tmpl"),
    # 6. 模块级 str 模板的 .format 全关键字展开误报（同族 1/4/5，与
    #    Formatter.format(self, record) 同名异签名）：verdict_check.py
    #    级联豁免留痕 reason 模板（{count} 占位，evo b739713e 引入调用点
    #    时漏补豁免）与 verify_contract.py 缺省证据目录模板（{spec} 占位）。
    ("core/verdict_check.py", "format", "_ENGINE_CASCADE_EXEMPT_REASON"),
    ("core/verify_contract.py", "format", "DEFAULT_EVIDENCE_DIR_TEMPLATE"),
    # 7. add-dsh-adapter-integration 3.1：provider_circuit.py dsh 错误码
    #    改写表 template.format(message=message)（{message} 占位全关键字
    #    展开）——同族 1/4/5/6 的 str.format 误报（引入调用点时补豁免）。
    ("core/agent_runner/provider_circuit.py", "format", "template"),
    # 8. 同族 1/4/5/6/7 的 str.format 全关键字展开误报（与 Formatter.format
    #    (self, record) 同名异签名）：pipeline.py 场景 sid 兜底模板
    #    _SCENARIO_SID_FALLBACK_FMT.format(i=index)（{i} 具名占位，只能关键字
    #    展开）；browser.py 对话框收割回调的 task.exception()（asyncio.Task
    #    零参签名）与 core/logger.py Logger.exception(component, message)
    #    同名异签名（同族 3 的 stdlib 零参/单参形态）。
    ("core/pm_engine/verification/pipeline.py", "format", "_SCENARIO_SID_FALLBACK_FMT"),
    ("core/verify_engine/browser.py", "exception", "task"),
]


def _receiver_src(call: ast.Call) -> str:
    """调用接收者表达式的源码文本（白名单语义键的组成部分）。

    误报白名单以 `(相对路径, 方法名, 接收者表达式)` 为键，不含行号：豁免
    随代码行漂移，不再因上方插入而行号失配（2026-09-15 回归）。求值失败
    （如极端嵌套表达式）返回空串——退化为「接收者不可识别」，该调用不被
    任何接收者豁免（宁可多报不漏报）。
    """
    try:
        return ast.unparse(call.func.value)
    except Exception:  # noqa: BLE001 —— 反解析失败不穿透扫描
        return ""


def scan_arity(prod_files, seams, whitelist) -> list:
    """扫描生产调用点，返回违规描述列表（已应用白名单）。

    违规描述格式：`文件:行 类.方法 调用给 N 个 / 要求 M 个`。
    """
    param_names = seam_param_names(prod_files, seams)
    violations = []
    for f in prod_files:
        if is_vendored(f):
            continue
        tree = parse_tree(f)
        if tree is None:
            continue
        rel = _rel(f)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)):
                continue
            method = node.func.attr
            if method not in seams:
                continue
            # *args / **kwargs 展开：实参数量静态不可知，不判定
            if any(isinstance(a, ast.Starred) for a in node.args):
                continue
            if any(k.arg is None for k in node.keywords):
                continue
            req = seams[method][0]
            provided = len(node.args)
            for k in node.keywords:
                if k.arg in param_names.get(method, ()):
                    provided += 1
            if provided >= req:
                continue
            if (rel, method, _receiver_src(node)) in whitelist:
                continue
            cname = _enclosing_class_name(tree, node)
            violations.append(
                f"{rel}:{node.lineno} {cname}.{method} "
                f"调用给 {provided} 个 / 要求 {req} 个")
    return violations


def _enclosing_class_name(tree, call: ast.Call) -> str:
    """返回 call 节点所属的类名；模块级调用返回 "module"。

    取「包含该调用行号且跨度最小」的类（最内层）。位置跨度用
    lineno/end_lineno 判定，避免依赖 ast.walk 的遍历顺序。
    """
    best = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        end = node.end_lineno or node.lineno
        if node.lineno <= call.lineno <= end:
            if best is None or (end - node.lineno) < (best[1] - best[0]):
                best = (node.lineno, end, node.name)
    return best[2] if best else "module"


def _write_temp_py(root: Path, rel: str, source: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source, encoding="utf-8")
    return p


SEAM_SOURCE = (
    "class PMEngine:\n"
    "    def handle_event(self, event_kind, spec_name, spec_entry):\n"
    "        pass\n"
    "    def optional_method(self, a, b=1):\n"
    "        pass\n"
    "    def vararg_method(self, a, *args):\n"
    "        pass\n"
)


class TestCallsiteArityGuard(unittest.TestCase):
    """R1/R2 单测：注入样例 → 违规/合规判定符合预期。"""

    def _scan(self, call_source: str, whitelist=None, seam_source=SEAM_SOURCE):
        """写临时 seam 文件 + 调用文件，对两者一起运行守卫。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seam_file = _write_temp_py(root, "core/_seams.py", seam_source)
            call_file = _write_temp_py(root, "core/_calls.py", call_source)
            sigs = index_method_signatures([seam_file])
            seams = unique_seams(sigs)
            return scan_arity([seam_file, call_file], seams, whitelist or [])

    def test_arity_violation_reported(self):
        """实参不足被拦截：2 个实参调用 3 必填 → 违规。"""
        violations = self._scan(
            "from core._seams import PMEngine\n"
            "pm = PMEngine()\n"
            "class Consumer:\n"
            "    def go(self):\n"
            "        pm.handle_event('spec_implemented', 'demo')\n")
        self.assertEqual(len(violations), 1)
        self.assertIn("Consumer.handle_event 调用给 2 个 / 要求 3 个",
                      violations[0])

    def test_keyword_completion_not_flagged(self):
        """关键字补足不误报：位参由关键字满足 → 不判违规。"""
        violations = self._scan(
            "from core._seams import PMEngine\n"
            "pm = PMEngine()\n"
            "class Consumer:\n"
            "    def go(self, spec, entry):\n"
            "        pm.handle_event('spec_implemented', spec, spec_entry=entry)\n"
            "        pm.handle_event(event_kind='x', spec_name='y', spec_entry=entry)\n")
        self.assertEqual(violations, [])

    def test_optional_param_default_satisfied_by_one(self):
        """可选位参计数正确：`optional_method(a, b=1)` 传 1 个即合规。"""
        violations = self._scan(
            "from core._seams import PMEngine\n"
            "pm = PMEngine()\n"
            "class Consumer:\n"
            "    def go(self):\n"
            "        pm.optional_method('x')\n"
            "        pm.optional_method('x', 2)\n")
        self.assertEqual(violations, [])

    def test_starred_expansion_not_flagged(self):
        """*args / **kwargs 展开不误报：实参数量静态不可知。"""
        violations = self._scan(
            "from core._seams import PMEngine\n"
            "pm = PMEngine()\n"
            "class Consumer:\n"
            "    def go(self, args, kw):\n"
            "        pm.handle_event(*args)\n"
            "        pm.handle_event(**kw)\n")
        self.assertEqual(violations, [])

    def test_same_name_multiple_signatures_excluded(self):
        """同名多签名不参与：候选 seam 不含该名，任何调用都不判。"""
        violations = self._scan(
            "class Consumer:\n"
            "    def go(self):\n"
            "        self.get('only-key')\n",
            seam_source=(
                "class A:\n"
                "    def get(self, key):\n"
                "        pass\n"
                "class B:\n"
                "    def get(self, key, default):\n"
                "        pass\n"))
        self.assertEqual(violations, [])

    def test_whitelist_exact_exemption(self):
        """白名单精确豁免：该行不再计违规；白名单外同名调用仍判定。"""
        call_source = (
            "from core._seams import PMEngine\n"
            "pm = PMEngine()\n"
            "class Consumer:\n"
            "    def go(self):\n"
            "        pm.handle_event('spec_implemented', 'demo')  # L1\n"
            "    def go2(self):\n"
            "        svc.handle_event('spec_implemented', 'demo2')  # L2\n")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seam_file = _write_temp_py(root, "core/_seams.py", SEAM_SOURCE)
            call_file = _write_temp_py(root, "core/_calls.py", call_source)
            sigs = index_method_signatures([seam_file])
            seams = unique_seams(sigs)
            # 语义键（接收者 pm）：L1 豁免；不同接收者 svc 的 L2 仍报
            whitelist = [(_rel(call_file), "handle_event", "pm")]
            violations = scan_arity([seam_file, call_file], seams, whitelist)
        self.assertEqual(len(violations), 1)
        self.assertIn("handle_event 调用给 2 个 / 要求 3 个", violations[0])
        # 白名单外同名调用仍正常判定（非文件级/全局豁免）
        self.assertIn("Consumer.handle_event", violations[0])

    def test_whitelist_semantic_key_immune_to_line_drift(self):
        """语义键（接收者+方法名）豁免免疫行号漂移。

        回归（2026-09-15）：白名单曾以 `(相对路径, 行号, 方法名)` 为键，
        core/evolution.py 在文件前部插入 39 行后 SPEC_YAML_TEMPLATE.format
        由 803 漂到 842，豁免失配 → 守卫误报红灯（fix-writepoint-anchor-drift
        记录的绝对行号反模式）。语义键下于调用点上方插入任意多无关行，
        豁免照常命中。
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seam_file = _write_temp_py(root, "core/_seams.py", SEAM_SOURCE)
            # 同一调用点，上方垫 40 行无关代码（制造行号漂移）
            padded = (
                "# pad\n" * 40
                + "from core._seams import PMEngine\n"
                + "pm = PMEngine()\n"
                + "class Consumer:\n"
                + "    def go(self):\n"
                + "        pm.handle_event('spec_implemented', 'demo')\n")
            call_file = _write_temp_py(root, "core/_calls.py", padded)
            sigs = index_method_signatures([seam_file])
            seams = unique_seams(sigs)
            whitelist = [(_rel(call_file), "handle_event", "pm")]
            violations = scan_arity([seam_file, call_file], seams, whitelist)
        self.assertEqual(violations, [])


class TestArityGuardTeeth(unittest.TestCase):
    """R3 有牙自检：候选方法集规模高于下限，防止规则退化后永远绿。"""

    # 候选集规模下限：实测当前 core/ 唯一签名无变长参数候选约 850+，
    # 保守下限取 100——任何候选构造规则错误退化为近空集都会在此失败。
    CANDIDATE_LOWER_BOUND = 100

    def test_candidate_set_is_large_enough(self):
        core_files = _core_files()
        self.assertTrue(core_files, "core/ 扫描目标为空，守卫已失效")
        sigs = index_method_signatures(core_files)
        seams = unique_seams(sigs)
        self.assertGreaterEqual(
            len(seams), self.CANDIDATE_LOWER_BOUND,
            f"候选方法集退化为 {len(seams)}（< {self.CANDIDATE_LOWER_BOUND}），"
            "守卫已失效：请检查候选 seam 构造规则")

    def test_scan_targets_non_empty(self):
        self.assertTrue(_prod_files(), "生产扫描目标为空，守卫已失效")

    def test_node_modules_vendored_excluded(self):
        """vendored 代码（node_modules）不参与扫描，否则第三方构建脚本
        （katex parse_tfm.py 等）会灌入大量无关方法名。"""
        vendored = [
            f for f in (REPO_ROOT / "core").rglob("*.py")
            if any(m in f.as_posix() for m in VENDORED_DIR_MARKERS)
        ]
        self.assertTrue(
            vendored,
            "预期 core/dashboard/static/node_modules 下存在 vendored py，"
            "排除逻辑失效应回归误报")


class TestArityGuardOnRepo(unittest.TestCase):
    """落地实证：对当前 core/ + fenixd.py 运行守卫，白名单外违规数 = 0。

    事故根因调用点（admin_monitor.handle_event 2 参）已被防线三 3.4 修正为
    3 参；本测试钉住「生产调用点实参必填位」的静态契约，防止回归。
    """

    def test_current_production_has_zero_non_whitelist_violations(self):
        core_files = _core_files()
        seams = unique_seams(index_method_signatures(core_files))
        violations = scan_arity(_prod_files(), seams, ARITY_WHITELIST)
        self.assertEqual(
            violations, [],
            "生产调用点出现实参必填位不足:\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
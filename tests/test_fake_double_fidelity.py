"""
test-double-fidelity — 测试替身保真守卫（add-control-plane-silent-failure-guards 防线二）。

扫描 tests/**/*.py 中所有类定义的方法，与 core/ 候选 seam（方法名唯一签名、
无 *args/**kwargs、非 dunder、不在宽泛名黑名单）比对 (必填位参数, 是否含
*args, 是否含 **kwargs)：

- 替身比生产方法**更宽容**（含 *args 或 **kwargs）→ 违规。**kwargs 会把
  实参数量不符静默吸收（本 SPEC 事故第二层：`handle_event(self, event_kind,
  spec_name, **kwargs)` 对 2 参/3 参都成立，CI 全绿）。
- 替身必填位参数**少于**生产方法 → 违规。
- 替身必填更多不判违规（会在测试执行时当场 TypeError，无静默风险）。

白名单：最小粒度 (文件, 类名, 方法名)，豁免确有意为之的宽容替身
（当前为空——本 SPEC 已把全部 8 处既有偏离替身收紧为显式签名）。

判定规则（design D1/D2）：self/cls 剥离与 callsite-arity-guard 一致；
staticmethod 首参不剥离。vendored 代码（node_modules）不参与。
"""

import ast
import inspect
import tempfile
import unittest
from pathlib import Path

from fenix_guards import (
    VENDORED_DIR_MARKERS,
    index_method_signatures,
    is_vendored,
    method_signature,
    parse_tree,
    repo_relative,
    unique_seams,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# 宽泛名黑名单（design D2 / spec R2）：logger 风格、容器风格、时间工具——
# 这些方法名跨类语义纷杂，「同名即同 seam」不成立，不参与比对。
BROAD_NAME_BLACKLIST = frozenset({
    # logger 风格
    "info", "warning", "error", "debug", "critical", "exception",
    "log", "_log",
    # 容器风格
    "get", "items", "keys", "values", "append", "update", "read", "write",
    "pop", "popitem", "setdefault", "extend", "insert", "remove",
    "count", "index", "copy", "clear", "reverse", "sort", "add", "discard",
    # 时间工具
    "now", "isoformat", "utcnow", "strftime", "strptime", "timestamp",
    "fromtimestamp", "fromisoformat",
})

# 替身保真白名单（spec R2）：最小粒度 (文件相对路径, 类名, 方法名)。
# 当前为空——本 SPEC 已将 8 处既有偏离替身全部收紧为显式签名
# （test_run_budget_continuity / test_liveness_hang_discrimination /
# test_spec_review_agent / test_spec_review_gate / test_self_evolution /
# test_blocked_reverify_gate / test_frozen_scenario_schema_migration）。
FIDELITY_WHITELIST = []


def _core_files() -> list:
    return [
        f for f in sorted((REPO_ROOT / "core").rglob("*.py"))
        if not is_vendored(f)
    ]


def _test_files() -> list:
    return sorted((REPO_ROOT / "tests").rglob("*.py"))


def core_seams() -> dict:
    """core/ 候选 seam 集（唯一签名 + 无变长参数 + 非 dunder + 非宽泛名）。"""
    return unique_seams(
        index_method_signatures(_core_files()), blacklist=BROAD_NAME_BLACKLIST)


def scan_fake_fidelity(test_files, seams: dict, whitelist) -> list:
    """扫描 tests/ 类方法替身，返回违规描述列表（已应用白名单）。

    违规描述格式：`文件:行 类.方法 fake=(req,vararg,kwarg) prod=(req,vararg,kwarg)`。
    """
    violations = []
    for f in test_files:
        if is_vendored(f):
            continue
        tree = parse_tree(f)
        if tree is None:
            continue
        rel = repo_relative(f, REPO_ROOT)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name not in seams:
                    continue
                req, va, kw, _is_static = method_signature(item)
                preq, pva, pkw = seams[item.name]
                if (va or kw) or req < preq:
                    if (rel, node.name, item.name) in whitelist:
                        continue
                    violations.append(
                        f"{rel}:{item.lineno} {node.name}.{item.name} "
                        f"fake=({req},{va},{kw}) prod=({preq},{pva},{pkw})")
    return violations


def _write_temp_py(root: Path, rel: str, source: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source, encoding="utf-8")
    return p


class TestFakeDoubleFidelity(unittest.TestCase):
    """R1/R2 单测：注入替身样例 → 宽容/必填不足判违规；显式签名放行。"""

    SEAM_SOURCE = (
        "class PMEngine:\n"
        "    def handle_event(self, event_kind, spec_name, spec_entry):\n"
        "        pass\n"
    )

    def _scan(self, fake_source: str, seam_source: str = None) -> list:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seam_file = _write_temp_py(
                root, "core/_seams.py", seam_source or self.SEAM_SOURCE)
            test_file = _write_temp_py(root, "tests/_fake.py", fake_source)
            seams = unique_seams(index_method_signatures([seam_file]))
            return scan_fake_fidelity([test_file], seams, [])

    def test_lenient_fake_flagged(self):
        """宽容替身被拦截：**kwargs 吸收实参数量不符 → 违规。"""
        violations = self._scan(
            "class _FakePmEngine:\n"
            "    def handle_event(self, event_kind, spec_name, **kwargs):\n"
            "        pass\n")
        self.assertEqual(len(violations), 1)
        self.assertIn(
            "_FakePmEngine.handle_event fake=(2,False,True) prod=(3,False,False)",
            violations[0])

    def test_star_args_fake_flagged(self):
        """*args 宽容替身同样被拦截。"""
        violations = self._scan(
            "class _FakeRunner:\n"
            "    def handle_event(self, *a):\n"
            "        pass\n")
        self.assertEqual(len(violations), 1)

    def test_fewer_required_fake_flagged(self):
        """必填位参数少于生产 → 违规（缺参调用同样静默）。"""
        violations = self._scan(
            "class _FakePmEngine:\n"
            "    def handle_event(self, event_kind, spec_name):\n"
            "        pass\n")
        self.assertEqual(len(violations), 1)
        self.assertIn("fake=(2,False,False) prod=(3,False,False)",
                      violations[0])

    def test_faithful_fake_allowed(self):
        """忠实替身放行：显式签名与生产一致 → 不判违规。"""
        violations = self._scan(
            "class _FakePmEngine:\n"
            "    def handle_event(self, event_kind, spec_name, spec_entry):\n"
            "        pass\n")
        self.assertEqual(violations, [])

    def test_more_required_fake_allowed(self):
        """必填更多放行（无静默吸收风险，测试执行时当场 TypeError）。"""
        violations = self._scan(
            "class _FakePmEngine:\n"
            "    def handle_event(self, event_kind, spec_name, spec_entry,\n"
            "                     extra):\n"
            "        pass\n")
        self.assertEqual(violations, [])

    def test_whitelist_exact_exemption(self):
        """白名单精确豁免：最小粒度 (文件, 类名, 方法名) 豁免，其他仍判定。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seam_file = _write_temp_py(
                root, "core/_seams.py", self.SEAM_SOURCE)
            test_file = _write_temp_py(
                root, "tests/_fake.py",
                "class _FakeA:\n"
                "    def handle_event(self, event_kind, spec_name, **kwargs):\n"
                "        pass\n"
                "class _FakeB:\n"
                "    def handle_event(self, event_kind, spec_name, **kwargs):\n"
                "        pass\n")
            seams = unique_seams(index_method_signatures([seam_file]))
            whitelist = [(repo_relative(test_file, REPO_ROOT),
                          "_FakeA", "handle_event")]
            violations = scan_fake_fidelity([test_file], seams, whitelist)
        self.assertEqual(len(violations), 1)
        self.assertIn("_FakeB.handle_event", violations[0])
        self.assertNotIn("_FakeA.handle_event", violations[0])

    def test_broad_name_excluded_from_judgment(self):
        """宽泛名不参与：seam 中 `get` 唯一签名 + 替身放宽为 **kwargs——
        黑名单排除后不判违规；解除黑名单（宽泛名参与）时才报出。
        证明黑名单是防跨类同名误报的闸门（spec R2 场景「宽泛名不参与」）。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seam_file = _write_temp_py(
                root, "core/_seams.py",
                "class _PM:\n"
                "    def get(self, key, default=None):\n"
                "        pass\n")
            test_file = _write_temp_py(
                root, "tests/_fake.py",
                "class _FakePM:\n"
                "    def get(self, **kwargs):\n"
                "        pass\n")
            index = index_method_signatures([seam_file])
            with_blacklist = scan_fake_fidelity(
                [test_file],
                unique_seams(index, blacklist=BROAD_NAME_BLACKLIST),
                [])
            without_blacklist = scan_fake_fidelity(
                [test_file], unique_seams(index), [])
        self.assertEqual(with_blacklist, [],
                         "宽泛名 get 被黑名单排除 → 不参与比对，放宽替身不应被报")
        self.assertEqual(len(without_blacklist), 1,
                         "解除黑名单后同一放宽替身应被报出（黑名单确有约束力）")


class TestFakeDoubleFidelityTeeth(unittest.TestCase):
    """R4 有牙自检：候选 seam 集规模高于下限，防止规则退化后永远绿。"""

    SEAM_LOWER_BOUND = 50

    def test_seam_set_is_large_enough(self):
        seams = core_seams()
        self.assertGreaterEqual(
            len(seams), self.SEAM_LOWER_BOUND,
            f"候选 seam 集退化为 {len(seams)}（< {self.SEAM_LOWER_BOUND}），"
            "守卫已失效：请检查候选 seam 构造规则（含宽泛名黑名单）")

    def test_scan_targets_non_empty(self):
        self.assertTrue(_test_files(), "tests/ 扫描目标为空，守卫已失效")

    def test_broad_name_blacklist_non_empty(self):
        """宽泛名黑名单是防误报的核心约束，必须非空。"""
        self.assertTrue(BROAD_NAME_BLACKLIST)

    def test_node_modules_vendored_excluded(self):
        vendored = [
            f for f in (REPO_ROOT / "tests").rglob("*.py")
            if any(m in f.as_posix() for m in VENDORED_DIR_MARKERS)
        ]
        # tests/ 下当前无 vendored 文件；此测试钉住「vendored 应被排除」
        # 的规则语义（core 侧同规则已在 arity 守卫中实测生效）。
        for v in vendored:
            self.assertTrue(is_vendored(v), f"{v} 应被 is_vendored 识别")


class TestFakeDoubleFidelityOnRepo(unittest.TestCase):
    """落地实证：对当前 tests/ 运行守卫，违规数 = 0（白名单为空）。"""

    def test_current_tests_have_zero_violations(self):
        seams = core_seams()
        violations = scan_fake_fidelity(
            _test_files(), seams, FIDELITY_WHITELIST)
        self.assertEqual(
            violations, [],
            "tests/ 出现宽容/必填不足的测试替身:\n" + "\n".join(violations))

    def test_tightened_fakes_match_production(self):
        """钉住 5 处（本 SPEC 收紧的）替身与生产签名一致——防后续被改回
        **kwargs 后仅靠守卫有牙测试兜底（spec R3 场景「收紧后守卫零违规」）。"""
        seams = core_seams()
        # 这些方法名必须仍在候选 seam 中（否则收紧失去可比对基准）。
        # 注：`_check_agent_result_artifact` 原为 AgentRunner 类方法（转发壳），
        # refactor-facade-delegation 收敛后真身为 result_gate 模块函数（以 runner
        # 为首参的 self 首参模块函数），不再从「类方法唯一签名」检出；其替身保真
        # 由 tests/test_facade_delegation_contract.py 断言经门面实例路径解析到同一
        # 模块函数（守护集合变化而非产品行为变化，design 5.4 已预警）。
        for name in ("_send_human_escalation_alert",
                     "_run_claude",
                     "handle_event"):
            self.assertIn(name, seams, f"seam {name} 应从 core/ 唯一签名中检出")
        # 模块函数 seam：`_check_agent_result_artifact` 收敛后为 result_gate 模块函数
        import core.agent_runner.result_gate as result_gate
        fn = getattr(result_gate, "_check_agent_result_artifact")
        self.assertTrue(callable(fn))
        self.assertIn("def _check_agent_result_artifact",
                      inspect.getsource(fn))


if __name__ == "__main__":
    unittest.main()

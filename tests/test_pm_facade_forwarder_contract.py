"""门面转发契约硬门（evo-fix-pm-facade-drift-forwarder-contract）。

终结「真身在 mixin 上、门面忘转发」类事故：生产调用点经 self._pm 走门面，
而 _FORWARDER_REGISTRY 漏登记时 __getattr__ 查表未命中即抛 AttributeError，
被 _run_agent_worker 函数级 try 兜住后整轮派发回滚、retryable 退避重派，
白烧 run 预算。复发前科 x2：_disputed_deliverables / _preclassify_drift
（后者致交付物争议漂移分支必崩回滚）。

契约（design D1-D3）：
- 正扫（ast.Attribute 链，非运行时枚举——D1：运行时 dir() 实例枚举会因惰性
  property 触发构造，误伤面大）：core/ 下全部 ``self._pm.<name>`` 字面引用点
  （调用与非调用属性访问——如 ``with self._pm._queue_lock:``，门面消费点不止
  调用形态）按目录分桶，逐名断言可经对应门面解析；解析域 = 注册表键 ∪ 门面
  与混入类显式定义（类体 def/类属性赋值，dir() 覆盖）∪ 方法体内
  ``self.<名> = ...`` 实例属性赋值（AST 推导，_queue_lock/_running_agents 等
  ——推导漏了实例属性必自伤）；dunder 除外；失败输出缺失名与调用文件:行号。
- 扫描边界（design 风险节）：``getattr(self._pm, "<名>", default)`` 探测形态
  （prompt_builder.py / provider_circuit.py 等现存 4 处，均带 default、属可选
  能力探测语义；另 family.py 有 getattr(self._pm.agent_runner, ...) 子对象
  形态）不是硬契约调用点，无 self._pm.<名> 属性链，天然不在扫描范围——此
  边界为本测试的显式声明，非遗漏。直接属性链里的 fail-soft 子对象探测
  （_EXPLICIT_EXEMPT，design D2「显式名单为辅」）以显式豁免处理，理由随名单
  注释。
- 反扫：注册表每条目按各自形态解析，无悬空条目。全仓三张同构注册表条目形态
  不同（PMEngine 二元组 / AgentRunner 二元组与 self 首参模块函数并存 /
  VerificationPipeline ``名: 模块函数`` 单值），(sub_attr, meth) 解包 MUST NOT
  跨形态机械套用，按条目形态分支断言。
- VerificationPipeline 门：core/pm_engine/verification/** 现状零
  self._pm._<private> 回引（context.py 契约目标：组件依赖一律经
  PipelineContext 承载）——正扫空集，书面说明于此；未来出现回引即失败。
"""

import ast
import functools
import inspect
import logging
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.agent_runner.runner import AgentRunner
from core.pm_engine.engine import PMEngine
from core.pm_engine.verification.pipeline import VerificationPipeline

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "core"

# 目录分桶（design D2）：core/<前缀>/** 的 self._pm 回引归对应门面检查。
# liveness.py 等组件的 self._pm 回引的是 AgentRunner（其 _running_agents 在
# PMEngine 上不存在），混扫必误报——按目录分桶归各自门。
_BUCKETS = {
    "core/pm_engine": PMEngine,
    "core/agent_runner": AgentRunner,
}

# 显式豁免名单（design D2：豁免清单以「门面类与混入类显式定义」自动推导为主、
# 显式名单为辅；变更 MUST 附注释理由，失败信息按 注册表/显式/豁免 三归属可辨）。
# AgentRunner 无 .agent_runner 实例属性（fenixd.py 的 self.agent_runner 是
# daemon 宿主的，非 runner 的）：prompt_builder.py:1092 的
# ``self._pm.agent_runner.worktree_manager...`` 包在 try/except Exception 内，
# AttributeError 被吞、branch 保持 None——与 getattr(..., default) 同属可选
# 能力探测语义（fail-soft 子对象形态），非硬契约调用点。
_EXPLICIT_EXEMPT = {
    "core/agent_runner": {
        "agent_runner": ("prompt_builder.py:1092 fail-soft 子对象探测"
                         "（try/except 吞 AttributeError，branch 保持 None）"),
    },
}


@functools.lru_cache(maxsize=None)
def _scan_pm_references():
    """AST 扫描 core/**.py 全部 ``self._pm.<name>`` 字面属性引用。

    返回 [(relpath, lineno, name)] 元组。只收接收链字面为 ``self._pm`` 的
    ast.Attribute（取紧邻 _pm 的第一个属性名；``self._pm._x._y`` 只收 _x）；
    ``getattr(self._pm, 名, default)`` 探测形态无属性链，天然不在内（见模块
    docstring 扫描边界声明）。
    """
    refs = []
    for path in sorted(CORE_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            recv = node.value
            if (isinstance(recv, ast.Attribute) and recv.attr == "_pm"
                    and isinstance(recv.value, ast.Name)
                    and recv.value.id == "self"):
                refs.append((rel, node.lineno, node.attr))
    return tuple(refs)


@functools.lru_cache(maxsize=None)
def _facade_resolution_domain(cls):
    """门面解析域 = 注册表键 ∪ 显式定义（design D2，豁免以此自动推导）。

    - 类体 def / 类属性赋值 / staticmethod 别名 / 惰性 property：``dir(cls)``
      覆盖（含 MRO 混入类继承；dir 只列名不访问类属性，不触发惰性构造）。
    - 方法体内 ``self.<名> = ...`` 实例属性赋值（QQQueueMixin.__init__ 的
      _queue_lock/_run_queue、AgentRunner 的 _running_agents 等）：对 MRO
      各类源码 AST 推导。
    """
    names = set(cls._FORWARDER_REGISTRY) | set(dir(cls))
    for klass in cls.__mro__:
        try:
            src = inspect.getsource(klass)
        except (OSError, TypeError):
            continue  # builtins / 无源码类
        for node in ast.walk(ast.parse(textwrap.dedent(src))):
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            else:
                continue
            for t in targets:
                if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                        and t.value.id == "self"):
                    names.add(t.attr)
    return names


def _fmt_sites(sites):
    return "\n".join(f"  {name}  ({rel}:{line})" for rel, line, name in sites)


def _make_pm(tmp: Path) -> PMEngine:
    """最小可用 PMEngine（对齐 test_tasksmd_relint_gate 的构造形态）。"""
    return PMEngine(MagicMock(), MagicMock(), {}, tmp,
                    logging.getLogger("fenix-test-facade-contract"))


def _make_runner(tmp: Path) -> AgentRunner:
    """最小 AgentRunner（__new__ 绕过 __init__，对齐 test_code_fix._make_runner）。"""
    r = AgentRunner.__new__(AgentRunner)
    r.config = {}
    r.worktree_manager = None
    r.state_machine = None
    r.project_root = tmp
    r.logger = logging.getLogger("fenix-test-facade-contract")
    r._running_agents = {}
    return r


class TestPreclassifyDriftForwarder(unittest.TestCase):
    """漂移预分类经门面可达（spec Requirement「漂移预分类经门面可达」）。"""

    def test_registry_entry_adjacent_to_orphan(self):
        """_preclassify_drift 与裁决组 _preclassify_orphan 相邻、键值形态同款。"""
        reg = PMEngine._FORWARDER_REGISTRY
        self.assertEqual(reg.get("_preclassify_drift"),
                         ("_dispatcher", "_preclassify_drift"),
                         "注册表条目 MUST 逐字为 (\"_dispatcher\", \"_preclassify_drift\")")
        self.assertIsInstance(reg["_preclassify_drift"], tuple,
                              "键值形态 MUST 与现有条目同款（二元组）")
        keys = list(reg)
        self.assertEqual(keys.index("_preclassify_orphan") + 1,
                         keys.index("_preclassify_drift"),
                         "MUST 紧跟 _preclassify_orphan（裁决组保持相邻可读）")

    def test_facade_forwards_to_dispatcher_truth(self):
        """经门面调用 _preclassify_drift 转发到 Dispatcher（VAdjudicationMixin）真身。"""
        from core.pm_engine.dispatch import Dispatcher
        from core.pm_engine.dispatch.adjudication import VAdjudicationMixin

        with tempfile.TemporaryDirectory() as td:
            pm = _make_pm(Path(td))
            forwarded = pm._preclassify_drift  # __getattr__ 注册表转发路径
        self.assertTrue(callable(forwarded))
        self.assertIs(forwarded.__func__, VAdjudicationMixin._preclassify_drift,
                      "真身 MUST 是 VAdjudicationMixin._preclassify_drift")
        self.assertIs(forwarded.__func__, Dispatcher._preclassify_drift,
                      "经 Dispatcher 门面取得的是同一实现体")

    def test_forwarded_signature_matches_production_call_site(self):
        """五参签名与生产调用点（queue.py 争议分支位置传参形态）一致。"""
        from core.pm_engine.dispatch.adjudication import VAdjudicationMixin

        params = list(inspect.signature(VAdjudicationMixin._preclassify_drift).parameters)
        self.assertEqual(params,
                         ["self", "spec_name", "result", "impl_result",
                          "disputed", "missing"],
                         "MUST 保持三预分类器统一签名（queue.py 以同形态位置传参）")


class TestFacadeCallSiteCoverage(unittest.TestCase):
    """调用点覆盖性契约硬门（spec Requirement「门面调用点覆盖性契约硬门」正扫）。"""

    def test_bucketed_call_sites_resolvable(self):
        """分桶正扫：每个 self._pm.<name> 都可经对应门面解析。"""
        for bucket in sorted(_BUCKETS):
            cls = _BUCKETS[bucket]
            domain = _facade_resolution_domain(cls)
            exempt = _EXPLICIT_EXEMPT.get(bucket, {})
            missing = sorted({(rel, line, name)
                              for rel, line, name in _scan_pm_references()
                              if rel.startswith(bucket + "/")
                              and not name.startswith("__")
                              and name not in domain
                              and name not in exempt})
            self.assertEqual(
                [], missing,
                f"{cls.__name__} 门存在不可解析的 self._pm.<name> 调用点"
                f"（归属三类均未命中：注册表键 / 门面显式定义 / 显式豁免名单——"
                f"真身在 mixin、门面忘转发即此形态）:\n"
                + _fmt_sites(missing))

    def test_all_call_sites_are_bucketed(self):
        """core/ 下全部调用点 MUST 落在已登记桶内（新组件门防漏检）。"""
        unbucketed = sorted({(rel, line, name)
                             for rel, line, name in _scan_pm_references()
                             if not any(rel.startswith(b + "/") for b in _BUCKETS)})
        self.assertEqual(
            [], unbucketed,
            "core/ 下存在未分桶的 self._pm.<name> 调用点——新组件门 MUST 在 "
            "_BUCKETS 登记后纳入解析域检查:\n" + _fmt_sites(unbucketed))


class TestRegistryEntriesResolvable(unittest.TestCase):
    """注册表反向断言（spec Requirement 反扫 + 同构注册表同门检查）。"""

    def test_pmengine_entries_resolvable(self):
        """PMEngine 二元组条目经惰性 property + getattr 链可解析，无悬空。"""
        with tempfile.TemporaryDirectory() as td:
            pm = _make_pm(Path(td))
            dangling = []
            for name, target in PMEngine._FORWARDER_REGISTRY.items():
                # PMEngine 形态基线：全表二元组 (sub_attr, meth)。
                self.assertIsInstance(
                    target, tuple,
                    f"{name!r}: PMEngine 注册表条目 MUST 为二元组形态"
                    f"（模块函数单值是 AgentRunner/VerificationPipeline 形态，勿混入）")
                sub_attr, meth = target
                try:
                    ok = hasattr(getattr(pm, sub_attr), meth)  # 惰性 property 构造
                except AttributeError:
                    ok = False
                if not ok:
                    dangling.append(f"  {name!r} -> ({sub_attr!r}, {meth!r})")
                else:
                    # 端到端：经门面 __getattr__ 转发路径同样可解析
                    self.assertTrue(hasattr(pm, name),
                                    f"{name!r} 经门面 __getattr__ 不可解析")
            self.assertEqual([], dangling,
                             "PMEngine 注册表存在悬空条目（指向不存在的子对象属性/方法）:\n"
                             + "\n".join(dangling))

    def test_agent_runner_entries_resolvable(self):
        """AgentRunner 条目按形态分支解析（二元组 / self 首参模块函数并存）。"""
        with tempfile.TemporaryDirectory() as td:
            r = _make_runner(Path(td))
            dangling = []
            for name, target in AgentRunner._FORWARDER_REGISTRY.items():
                if isinstance(target, tuple):
                    sub_attr, meth = target
                    try:
                        ok = hasattr(getattr(r, sub_attr), meth)
                    except AttributeError:
                        ok = False
                else:
                    # 模块函数单值形态：__getattr__ 以 partial(target, self)
                    # 转发——目标必须可调用且经门面可解析。
                    ok = callable(target)
                if not ok:
                    dangling.append(f"  {name!r} -> {target!r}")
                else:
                    self.assertTrue(hasattr(r, name),
                                    f"{name!r} 经门面 __getattr__ 不可解析")
            self.assertEqual([], dangling,
                             "AgentRunner 注册表存在悬空条目:\n" + "\n".join(dangling))

    def test_verification_pipeline_entries_resolvable(self):
        """VerificationPipeline 单值条目（名: 模块函数）形态基线 + 无悬空。

        (sub_attr, meth) 二元组解包不可跨形态机械套用：本表全为模块函数
        单值（__getattr__ 以 partial(func, self) 转发），出现 tuple 或
        不可调用值即形态漂移/悬空。
        """
        dangling = []
        for name, target in VerificationPipeline._FORWARDER_REGISTRY.items():
            if isinstance(target, tuple) or not callable(target):
                dangling.append(f"  {name!r} -> {target!r}")
        self.assertEqual([], dangling,
                         "VerificationPipeline 注册表存在悬空/形态漂移条目"
                         "（条目 MUST 为「名: 模块函数」单值）:\n" + "\n".join(dangling))

    def test_verification_side_zero_pm_private_backref(self):
        """VerificationPipeline 门正扫：现状零 self._pm._<private> 回引（书面说明）。

        core/pm_engine/verification/** 组件依赖一律经 PipelineContext 承载
        （context.py 契约目标，组件 MUST NOT 直接回引 pm 私有面）。现状正扫
        即空集——此为本契约的现状书面说明，不强行断言更多；未来出现回引
        即违反该契约，本测试失败。
        """
        backrefs = sorted({(rel, line, name)
                           for rel, line, name in _scan_pm_references()
                           if rel.startswith("core/pm_engine/verification/")
                           and name.startswith("_") and not name.startswith("__")})
        self.assertEqual(
            [], backrefs,
            "verification/** 出现 self._pm._<private> 回引（组件依赖 MUST 经 "
            "PipelineContext / pipeline 门面承载）:\n" + _fmt_sites(backrefs))

    def test_legitimate_non_registry_names_not_misreported(self):
        """合法不入表名字不误报：显式定义与静态式转发豁免清单均在解析域。"""
        # 豁免推导的「不误报」前提：这些名字确实不经注册表（断言防腐化）。
        self.assertNotIn("_instant_fail_cooled", PMEngine._FORWARDER_REGISTRY)
        self.assertNotIn("_queue_lock", PMEngine._FORWARDER_REGISTRY)
        self.assertNotIn("_extract_replan_error_items",
                         VerificationPipeline._FORWARDER_REGISTRY)
        # PMEngine 门面显式定义（方法 / property / staticmethod 链式别名 /
        # 实例属性）——豁免推导过窄会在此误报。
        pm_domain = _facade_resolution_domain(PMEngine)
        for name in ("_instant_fail_cooled", "_signal_kill_cooled", "_queue_lock",
                     "_run_queue", "_get_config", "_normalize_fail_signature"):
            self.assertIn(name, pm_domain,
                          f"门面显式定义 {name!r} 应在解析域（豁免推导过窄自伤）")
        # verification/pipeline.py 静态式转发豁免清单（首参非 pipe，MUST NOT
        # 入注册表——partial 会多注一个 self）：以类级别名保留解析路径，
        # 归 VerificationPipeline 解析域。
        pipe_domain = _facade_resolution_domain(VerificationPipeline)
        for name in ("_extract_replan_error_items", "_replan_errors_unconsumed",
                     "_normalize_fail_signature"):
            self.assertIn(name, pipe_domain,
                          f"静态式转发豁免名 {name!r} 应在 VerificationPipeline 解析域")


if __name__ == "__main__":
    unittest.main()

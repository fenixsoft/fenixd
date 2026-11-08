"""provider 引用校验单源化与分配失效划界（add-provider-validation-alert-governance）。

覆盖 tasks 1.4 / 2.3 / 2.2（3.2 的契约预检降噪见 test_contract_precheck_noise.py，
4.x supersede/cause 见 test_alert_supersede.py）：

- 相似名建议（规范化 + 编辑距离 ≤2 / 无候选输出注册表清单 / 确定性排序）；
- collect_unregistered_provider_refs 单源收集（str / 对象数组两形态、roles 过滤、
  形态非法跳过）；
- daemon 加载路径：未注册引用 → major 配置告警（cause=model-chain、指纹去重、
  evidence 含原始链条目、修复后自动复位、合法引用零变化）；
- Dashboard 保存路径拒绝语义回归（ValueError → 400，文案保留既有前缀 + 相似名
  建议）与两路径规则同源（同一 collect 实现）；
- 链解析三态单源（unassigned / invalid / ok，部分未注册照旧跳过保留既有语义）；
- runner 消费：分配失效不回落默认网关、按 [model-chain-unavailable] 归因、
  chain_exhausted 不计重试消耗、不触发 harness 回落 WARN；
- 无分配态回归：对称回落 + harness-default 一次性 WARN 语义不变（防互踩）。
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from core.admin_store import SIGNAL, AdminStore
from core.config import ConfigLoader
from core.dashboard.data import config_admin
from core.agent_runner import harness
from core.agent_runner.runner import AgentRunner

from tests.helpers import FakeLogger


def _write_project_config(proot: Path, cfg: dict) -> None:
    """写项目级 .fenix/config.yaml（加载路径 resolve_config 的读取点）。"""
    fenix = proot / ".fenix"
    fenix.mkdir(parents=True, exist_ok=True)
    (fenix / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8"
    )


def _providers(*names: str) -> list:
    """构造通过 _validate_llm 的最小合法 provider 注册表。"""
    return [
        {
            "name": n,
            "provider": "zhipu",
            "baseurl": "https://api.example.com",
            "apikey": "sk-test",
            "model": "glm-4",
        }
        for n in names
    ]


def _cfg(providers: list, models: dict | None = None) -> dict:
    cfg = {"llm": {"providers": providers}}
    if models is not None:
        cfg["agents"] = {"models": models}
    return cfg


class SuggestionTest(unittest.TestCase):
    """相似名建议（design D2）：规范化相等 / 编辑距离 ≤2 / 注册表清单兜底。"""

    def test_normalization_separator_drift_hits(self):
        # bigmodel.cn 与 bigmodel-cn 规范化后同为 bigmodel-cn（一字之差类坏名）
        self.assertEqual(
            ConfigLoader.suggest_registered_provider_name(
                "bigmodel.cn", ["bigmodel-cn"]
            ),
            "bigmodel-cn",
        )

    def test_edit_distance_threshold_hits(self):
        # 1 次替换（编辑距离 1 ≤ 2）
        self.assertEqual(
            ConfigLoader.suggest_registered_provider_name(
                "bigodel.cn", ["bigmodel.cn"]
            ),
            "bigmodel.cn",
        )
        # 距离 3 超阈值：不命中
        self.assertIsNone(
            ConfigLoader.suggest_registered_provider_name("zzzz", ["bigmodel.cn"])
        )

    def test_deterministic_tiebreak(self):
        # 两个候选都在阈值内 → 取（距离, 字典序）最小，保证确定性
        got = ConfigLoader.suggest_registered_provider_name(
            "aa", ["ab", "aac", "aaa"]
        )
        self.assertEqual(got, "aaa")

    def test_no_candidate_lists_registry(self):
        hint = ConfigLoader.describe_provider_ref_fix_hint("zzz", ["a", "b"])
        self.assertEqual(hint, "当前已注册 provider: a、b")

    def test_empty_registry_states_empty(self):
        hint = ConfigLoader.describe_provider_ref_fix_hint("zzz", [])
        self.assertEqual(hint, "当前未注册任何 provider（llm.providers 为空）")

    def test_normalize_is_total(self):
        # None / 非 str 输入不抛（登记名脏数据容错）
        self.assertEqual(ConfigLoader.normalize_provider_name_for_match(None), "")
        self.assertEqual(
            ConfigLoader.normalize_provider_name_for_match("A.B_C"), "a-b-c"
        )


class CollectSingleSourceTest(unittest.TestCase):
    """collect_unregistered_provider_refs：D1 校验单源（保存/加载两路径共用）。"""

    def setUp(self):
        self.config = _cfg(
            _providers("bigmodel.cn"),
            {
                "implementer": {"provider": "ghost-x"},
                "verifier": {"provider": ["bigmodel.cn", {"provider": "ghost-y"}]},
                "planner": {"provider": "bigmodel.cn"},
            },
        )

    def test_str_and_object_list_shapes_collected(self):
        report = ConfigLoader.collect_unregistered_provider_refs(self.config)
        self.assertEqual(report, {"implementer": ["ghost-x"], "verifier": ["ghost-y"]})

    def test_roles_filter_limits_scope(self):
        # Dashboard patch 校验只看本次提交的角色
        report = ConfigLoader.collect_unregistered_provider_refs(
            self.config, roles={"implementer"}
        )
        self.assertEqual(report, {"implementer": ["ghost-x"]})

    def test_invalid_shape_skipped_not_reported(self):
        # 形态非法（normalize ValueError）不在此判定：保存路径由
        # _validate_agent_models 拒绝、加载路径打日志
        self.config["agents"]["models"]["arbiter"] = {"provider": {"bad": 1}}
        report = ConfigLoader.collect_unregistered_provider_refs(self.config)
        self.assertNotIn("arbiter", report)

    def test_legal_refs_absent_from_report(self):
        report = ConfigLoader.collect_unregistered_provider_refs(
            _cfg(_providers("bigmodel.cn"), {"planner": {"provider": "bigmodel.cn"}})
        )
        self.assertEqual(report, {})


class LoadPathAlertTest(unittest.TestCase):
    """daemon 加载路径（resolve_config 尾部）：major 配置告警 + 指纹去重复位。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.proot = self.tmp / "proj"
        self.proot.mkdir()
        self.user_dir = self.tmp / "user"

    def _resolve(self, cfg: dict):
        with patch("core.config.USER_CONFIG_DIR", self.user_dir):
            return ConfigLoader.resolve_config(self.proot)

    def _records(self) -> list:
        store = AdminStore(self.proot)
        recs = store.read_all()
        return [
            r for r in recs if r.get("signal_type") == "provider_ref_invalid"
        ]

    def test_unregistered_ref_emits_major_alert(self):
        _write_project_config(
            self.proot,
            _cfg(
                _providers("bigmodel.cn"),
                {"implementer": {"provider": "bigmodel-cn", "model": "glm-4"}},
            ),
        )
        self._resolve({})
        recs = self._records()
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual(rec.get("kind"), SIGNAL)
        self.assertEqual(rec.get("severity"), "major")
        self.assertEqual(rec.get("cause"), "model-chain")
        self.assertEqual(rec.get("fingerprint"), "implementer:bigmodel-cn")
        self.assertIn("agents.models.implementer.provider", rec.get("description"))
        # D2：文案带相似名建议（description）；evidence 带注册表清单对账面
        self.assertIn("是否意指 bigmodel.cn", rec.get("description"))
        self.assertIn("当前已注册 provider=bigmodel.cn", rec.get("evidence"))

    def test_alert_evidence_contains_raw_chain_entry(self):
        # 分配失效告警 evidence 含原始链条目（排查可直接对账）
        raw = ["ghost-x", {"provider": "ghost-y"}]
        _write_project_config(
            self.proot,
            _cfg(_providers("bigmodel.cn"), {"verifier": {"provider": raw}}),
        )
        self._resolve({})
        recs = self._records()
        self.assertEqual(len(recs), 1)
        self.assertIn(json.dumps(raw, ensure_ascii=False), recs[0].get("evidence"))

    def test_fingerprint_dedup_and_auto_resolve_on_fix(self):
        cfg = _cfg(
            _providers("bigmodel.cn"),
            {"implementer": {"provider": "ghost-x"}},
        )
        _write_project_config(self.proot, cfg)
        self._resolve({})
        self.assertEqual(len(self._records()), 1)

        # 同指纹重载（热重载/重启）：不重发（账本未处理同指纹即跳过）
        self._resolve({})
        self.assertEqual(len(self._records()), 1)

        # 修复后重载：指纹消失 → 未处理同类型记录批量 auto-resolve
        _write_project_config(
            self.proot,
            _cfg(_providers("bigmodel.cn"), {"implementer": {"provider": "bigmodel.cn"}}),
        )
        self._resolve({})
        recs = self._records()
        self.assertEqual(len(recs), 1)
        self.assertTrue(recs[0].get("handled"))
        self.assertIn("自动复位", recs[0].get("resolve_note") or "")

    def test_legal_config_writes_no_alerts(self):
        # 合法引用零变化：不产告警、账本无该类型记录
        _write_project_config(
            self.proot,
            _cfg(_providers("bigmodel.cn"), {"planner": {"provider": "bigmodel.cn"}}),
        )
        self._resolve({})
        self.assertEqual(self._records(), [])
        # 复载一次仍零（复位半边对空账本零写回）
        self._resolve({})
        self.assertEqual(self._records(), [])


class DashboardSavePathTest(unittest.TestCase):
    """Dashboard 保存路径：拒绝语义回归 + 与加载路径同源（D1 单源）。

    _write_config_locked 是设置页 write_config 的实现入口：校验失败返回
    ``{"ok": False, "error": ...}``（路由层转 400），不抛 ValueError。
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "proj"
        # 存量基线：只带合法 llm 注册表（校验对象是本次 agents.models patch）
        _write_project_config(self.root, _cfg(_providers("bigmodel.cn")))

    def _patch_cfg(self, provider_value) -> dict:
        return {
            "agents": {
                "models": {"implementer": {"provider": provider_value, "model": "glm-4"}}
            }
        }

    def test_save_rejects_unregistered_with_hint(self):
        got = config_admin._write_config_locked(
            self.root, self._patch_cfg("bigmodel-cn")
        )
        self.assertFalse(got["ok"])
        msg = got["error"]
        # 既有前缀保留 + D2 建议段追加（规范化命中）
        self.assertIn("引用了不存在的 provider", msg)
        self.assertIn("bigmodel-cn", msg)
        self.assertIn("是否意指 bigmodel.cn", msg)
        # 拒绝后不得落盘：config.yaml 仍为存量内容（不含 agents 段）
        on_disk = yaml.safe_load(
            (self.root / ".fenix" / "config.yaml").read_text(encoding="utf-8")
        )
        self.assertNotIn("agents", on_disk)

    def test_save_accepts_registered_provider(self):
        got = config_admin._write_config_locked(
            self.root, self._patch_cfg("bigmodel.cn")
        )
        self.assertTrue(got["ok"], got)
        on_disk = yaml.safe_load(
            (self.root / ".fenix" / "config.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            on_disk["agents"]["models"]["implementer"]["provider"], "bigmodel.cn"
        )

    def test_two_paths_share_single_source(self):
        # 同源证据：保存路径与加载路径走同一个 collect 实现（monkeypatch 计数）
        calls = []
        orig = ConfigLoader.collect_unregistered_provider_refs

        def spy(cfg, roles=None):
            calls.append(roles)
            return orig(cfg, roles=roles)

        with patch.object(
            ConfigLoader, "collect_unregistered_provider_refs", staticmethod(spy)
        ):
            got = config_admin._write_config_locked(
                self.root, self._patch_cfg("ghost-x")
            )
        self.assertFalse(got["ok"])
        # patch 校验按本次提交角色限定调用（roles 过滤），证明单源被消费
        self.assertEqual(calls, [{"implementer"}])


class ChainResolutionTest(unittest.TestCase):
    """get_agent_chain_resolution 三态判定单源（design D3 划界）。"""

    def setUp(self):
        self.cfg = _cfg(
            _providers("bigmodel.cn"),
            {
                "implementer": {"provider": "ghost-x"},
                "planner": {"provider": "bigmodel.cn", "model": "glm-4"},
            },
        )

    def test_unassigned_when_no_entry(self):
        for cfg in (
            {},
            {"agents": {}},
            {"agents": {"models": {}}},
            {"agents": {"models": {"implementer": {"model": "glm-4"}}}},
            {"agents": {"models": {"implementer": {"provider": ""}}}},
        ):
            got = ConfigLoader.get_agent_chain_resolution(cfg, "implementer")
            self.assertEqual(
                got,
                {"status": "unassigned", "chain": [], "raw_provider": None},
                f"config={cfg}",
            )

    def test_invalid_when_all_entries_unregistered(self):
        got = ConfigLoader.get_agent_chain_resolution(self.cfg, "implementer")
        self.assertEqual(got["status"], "invalid")
        self.assertEqual(got["chain"], [])
        self.assertEqual(got["raw_provider"], "ghost-x")
        self.assertIn("ghost-x", got["invalid_reason"])

    def test_invalid_when_chain_shape_illegal(self):
        got = ConfigLoader.get_agent_chain_resolution(
            {"llm": {"providers": []},
             "agents": {"models": {"implementer": {"provider": {"bad": 1}}}}},
            "implementer",
        )
        self.assertEqual(got["status"], "invalid")
        self.assertIn("链形态非法", got["invalid_reason"])

    def test_ok_chain_and_partial_unknown_still_ok(self):
        got = ConfigLoader.get_agent_chain_resolution(self.cfg, "planner")
        self.assertEqual(got["status"], "ok")
        self.assertTrue(got["chain"])
        # 部分条目未注册：未知元素照旧跳过（既有运行期语义保留），状态 ok
        cfg = _cfg(
            _providers("bigmodel.cn"),
            {"verifier": {"provider": ["bigmodel.cn", "ghost-x"]}},
        )
        got = ConfigLoader.get_agent_chain_resolution(cfg, "verifier")
        self.assertEqual(got["status"], "ok")
        self.assertTrue(got["chain"])


class _RunnerStub:
    """_resolve_provider_candidate / _maybe_supersede_model_chain_alerts 最小替身。

    链解析方法直接借用 AgentRunner 未绑定实现（与生产同一代码路径，替身只
    提供 config/logger/指标收集面）；无 spawn/worktree 面——误入后续流程会
    AttributeError 显式失败，不会静默通过。
    """

    def __init__(self, config: dict):
        self.config = config
        self.logger = FakeLogger()
        self.project_root = Path(tempfile.gettempdir()) / "provider-ref-stub-proj"
        self.metrics = []

    _get_agent_model_assignment = AgentRunner._get_agent_model_assignment
    _get_agent_chain_resolution = AgentRunner._get_agent_chain_resolution
    _maybe_supersede_model_chain_alerts = AgentRunner._maybe_supersede_model_chain_alerts

    def _log_run_metrics(self, **kw):
        self.metrics.append(kw)

    def is_circuit_open(self, name, now=None):
        return False

    def _circuit_open_error(self, name):
        return f"provider circuit open: {name}"

    def _record_daily_provider_attempt(self, name):
        pass


def _attempt_state() -> SimpleNamespace:
    return SimpleNamespace(provider_name=None, model=None, chain_cursor=-1)


class RunnerInvalidChainTest(unittest.TestCase):
    """runner 消费分配失效：不回落默认网关、[model-chain-unavailable] 归因。"""

    def test_invalid_chain_fails_without_fallback(self):
        cfg = _cfg(
            _providers("bigmodel.cn"),
            {"implementer": {"provider": "ghost-x"}},
        )
        stub = _RunnerStub(cfg)
        provider, model, chain, early = AgentRunner._resolve_provider_candidate(
            stub, "spec-a", "implementer", "run-1", "run-1", 100.0, 0, {},
            _attempt_state(),
        )
        # 早退失败：不回落默认网关（provider/model 均空，early_result 在场）
        self.assertIsNone(provider)
        self.assertIsNone(model)
        self.assertEqual(chain, [])
        self.assertIsNotNone(early)
        self.assertFalse(early.success)
        self.assertTrue(early.chain_exhausted)  # 派发器跳过同因重派、不计重试消耗
        self.assertIn("[model-chain-unavailable]", early.error)
        self.assertIn("分配失效", early.error)
        self.assertIn("ghost-x", early.error)  # 原始链条目对账
        self.assertIn("agents.models.implementer.provider", early.error)  # 修复指引
        # 指标按 chain_exhausted 终态登记，provider/model 不冒登记
        self.assertEqual(stub.metrics[0]["terminal"], "chain_exhausted")
        self.assertIsNone(stub.metrics[0]["provider"])
        self.assertIsNone(stub.metrics[0]["model"])

    def test_unassigned_still_falls_back_to_default_gateway(self):
        # 回归（task 2.2）：无分配态维持既有语义——(None, None, chain, None)
        # 默认网关路径，无 early result（对称回落不拦派发）
        stub = _RunnerStub(_cfg(_providers("bigmodel.cn")))
        provider, model, chain, early = AgentRunner._resolve_provider_candidate(
            stub, "spec-a", "implementer", "run-1", "run-1", 100.0, 0, {},
            _attempt_state(),
        )
        self.assertIsNone(provider)
        self.assertIsNone(model)
        self.assertEqual(chain, [])
        self.assertIsNone(early)

    def test_partial_unknown_chain_still_selects(self):
        # 部分条目未注册：既有运行期跳过语义不变（链非空 → 走候选选择路径，
        # 选中首个未冷却候选，不进失效分支）
        cfg = _cfg(
            _providers("bigmodel.cn"),
            {"implementer": {"provider": ["bigmodel.cn", "ghost-x"], "model": "glm-4"}},
        )
        stub = _RunnerStub(cfg)
        stub._select_chain_candidate = lambda chain, spec, role: 0
        provider, model, chain, early = AgentRunner._resolve_provider_candidate(
            stub, "spec-a", "implementer", "run-1", "run-1", 100.0, 0, {},
            _attempt_state(),
        )
        self.assertIsNone(early)
        self.assertEqual(provider["name"], "bigmodel.cn")


class HarnessFallbackWarnRegressionTest(unittest.TestCase):
    """无分配回落 WARN 一次性语义回归（add-harness-default-key-fallback 2.1 不变）。"""

    def setUp(self):
        harness.reset_harness_default_fallback_warned()
        self.addCleanup(harness.reset_harness_default_fallback_warned)

    def test_warn_once_per_adapter(self):
        with self.assertLogs("fenixd.agent_runner.harness", level="WARNING") as cm:
            harness.warn_harness_default_fallback("claude", "implementer")
            harness.warn_harness_default_fallback("claude", "implementer")
        warns = [m for m in cm.output if "未分配 provider 链" in m]
        self.assertEqual(len(warns), 1)

    def test_invalid_chain_does_not_emit_fallback_warn(self):
        # 分配失效路径不 spawn（不登记 harness-default 回落形态）——adapter
        # 的一次性回落 WARN 天然不触发；runner 层直证无任何 harness WARNING。
        cfg = _cfg(
            _providers("bigmodel.cn"),
            {"implementer": {"provider": "ghost-x"}},
        )
        stub = _RunnerStub(cfg)
        with self.assertNoLogs("fenixd.agent_runner.harness", level="WARNING"):
            AgentRunner._resolve_provider_candidate(
                stub, "spec-a", "implementer", "run-1", "run-1", 100.0, 0, {},
                _attempt_state(),
            )


if __name__ == "__main__":
    unittest.main()

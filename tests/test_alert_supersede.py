"""告警根因标签与 supersede 批量失效（add-provider-validation-alert-governance 4.x）。

覆盖 tasks 4.1 / 4.2 / 4.4 / 4.6（4.3 前端呈现见 dashboard 源码与构建门）：

- cause 字段账本增量：append 带 cause 落库、非法 cause 归一 None；
  _make_signal 按封闭映射注入（verify_contract_missing→contract、
  daemon_errors→daemon-error、映射外→None 不臆造）；_signal_record 透传；
- supersede_by_cause：单事务批量原子（signal+escalation 双 kind 同批）、
  已处置/异根因不波及、unknown 根因硬拒不参与自动失效；
- revert_supersede：仅 superseded 态可人工撤销恢复未处理，其余终态拒回退；
- 触发观测点两半判据（design D5）：校验干净加载 + 派发成功实测（runner
  _maybe_supersede_model_chain_alerts）——校验不干净不触发；账本无目标零写回
  （mtime 不变，幂等可重入）；
- backfill_causes 存量回填：未处理无 cause 按高置信封闭映射推断 + 注记前缀、
  已有 cause/已处置/映射外不动、幂等（daemon 启动首轮一次性语义）。
"""

import tempfile
import unittest
from pathlib import Path

from core.admin_monitor import SIGNAL_CAUSE_MAP, AdminMonitor
from core.admin_store import (
    AUTO_RESOLVE_BY,
    DEFAULT_ALERT_CAUSE,
    SIGNAL,
    SUPERSEDED_BY,
    AdminStore,
)
from core.agent_runner.runner import AgentRunner

from tests.helpers import FakeLogger
from test_provider_ref_validation import _RunnerStub, _cfg, _providers


def _providers_registry():
    return _providers("bigmodel.cn")


class SupersedeStoreTest(unittest.TestCase):
    """supersede_by_cause / revert_supersede 存储层语义（tasks 4.2 / 4.4）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.proot = Path(tmp.name) / "proj"
        self.proot.mkdir()
        self.store = AdminStore(self.proot, FakeLogger())

    def _seed(self, cause=None, signal_type="provider_ref_invalid", kind=SIGNAL,
              fingerprint=None, spec=None, severity="major"):
        entry = {
            "kind": kind,
            "signal_type": signal_type,
            "spec": spec,
            "severity": severity,
            "description": "d",
            "evidence": "e",
        }
        if cause:
            entry["cause"] = cause
        if fingerprint:
            entry["fingerprint"] = fingerprint
        rec = self.store.append(entry)
        self.assertIsNotNone(rec)
        return rec

    def test_supersede_batch_is_atomic_across_kinds(self):
        mc1 = self._seed(cause="model-chain")
        mc2 = self._seed(cause="model-chain", kind="escalation")
        other = self._seed(cause="contract", signal_type="verify_contract_missing")
        nocause = self._seed()
        handled = self._seed(cause="model-chain")
        self.assertTrue(self.store.mark_signal_handled(handled["id"]))

        note = "模型链修复生效（观测点 model-chain：校验干净加载 + 派发成功）"
        count = self.store.supersede_by_cause("model-chain", note)
        # 双 kind 同批、已处置不重复计入
        self.assertEqual(count, 2)

        by_id = {r["id"]: r for r in self.store.read_all()}
        for rid in (mc1["id"], mc2["id"]):
            rec = by_id[rid]
            self.assertTrue(rec["handled"])
            self.assertEqual(rec["handled_by"], SUPERSEDED_BY)
            self.assertEqual(rec["resolve_note"], note)
            self.assertTrue(rec.get("handled_at"))
        # 异根因 / 无 cause / 已有终态不波及
        self.assertFalse(by_id[other["id"]]["handled"])
        self.assertFalse(by_id[nocause["id"]]["handled"])
        got = by_id[handled["id"]]
        self.assertTrue(got["handled"])
        self.assertNotEqual(got.get("handled_by"), SUPERSEDED_BY)

    def test_supersede_unknown_cause_hard_rejected(self):
        mc = self._seed(cause="model-chain")
        # unknown（DEFAULT_ALERT_CAUSE）与空值硬拒不参与自动失效（误归因防呆）
        self.assertEqual(self.store.supersede_by_cause(DEFAULT_ALERT_CAUSE, "n"), 0)
        self.assertEqual(self.store.supersede_by_cause("", "n"), 0)
        self.assertEqual(self.store.supersede_by_cause(None, "n"), 0)
        rec = {r["id"]: r for r in self.store.read_all()}[mc["id"]]
        self.assertFalse(rec["handled"])

    def test_revert_supersede_restores_unhandled(self):
        mc = self._seed(cause="model-chain")
        self.assertEqual(self.store.supersede_by_cause("model-chain", "note-x"), 1)

        self.assertTrue(self.store.revert_supersede(mc["id"]))
        rec = {r["id"]: r for r in self.store.read_all()}[mc["id"]]
        self.assertFalse(rec["handled"])
        self.assertIsNone(rec["handled_by"])
        self.assertIsNone(rec["handled_at"])
        self.assertIn("人工撤销", rec["resolve_note"])

    def test_revert_only_applies_to_superseded_state(self):
        # 其余终态（人工 resolved / auto-resolve）MUST NOT 经撤销入口回退
        resolved = self._seed(cause="contract")
        self.assertTrue(self.store.mark_signal_handled(resolved["id"]))
        auto = self._seed(signal_type="provider_ref_invalid", fingerprint="r:bad")
        self.store.auto_resolve_by_type_fingerprint(
            "provider_ref_invalid", set(), "n"
        )
        self.assertFalse(self.store.revert_supersede(resolved["id"]))
        self.assertFalse(self.store.revert_supersede(auto["id"]))
        self.assertFalse(self.store.revert_supersede("no-such-id"))
        by_id = {r["id"]: r for r in self.store.read_all()}
        self.assertEqual(by_id[auto["id"]]["handled_by"], AUTO_RESOLVE_BY)


class ObservationGateTest(unittest.TestCase):
    """_maybe_supersede_model_chain_alerts 触发观测点两半判据（task 4.2，D5）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.proot = Path(tmp.name) / "proj"
        self.proot.mkdir()
        self.store = AdminStore(self.proot, FakeLogger())
        self.stub = _RunnerStub(_cfg(_providers_registry()))
        self.stub.project_root = self.proot

    def _seed_model_chain(self, n=2):
        for i in range(n):
            self.store.append(
                {
                    "kind": SIGNAL,
                    "signal_type": "provider_ref_invalid",
                    "spec": None,
                    "severity": "major",
                    "cause": "model-chain",
                    "fingerprint": f"implementer:ghost-{i}",
                    "description": "d",
                    "evidence": "e",
                }
            )

    def _handled_ids(self):
        return {
            r["id"]: r
            for r in self.store.read_all()
            if r.get("handled_by") == SUPERSEDED_BY
        }

    def test_clean_config_and_ledger_triggers_supersede(self):
        self._seed_model_chain()
        self.stub._maybe_supersede_model_chain_alerts()
        self.assertEqual(len(self._handled_ids()), 2)

    def test_dirty_config_blocks_trigger(self):
        # 观测点不全（校验不干净：配置仍有未注册引用）→ 不触发，防误失效
        self._seed_model_chain()
        self.stub.config = {
            "llm": {"providers": _providers_registry()},
            "agents": {"models": {"implementer": {"provider": "ghost-x"}}},
        }
        self.stub._maybe_supersede_model_chain_alerts()
        self.assertEqual(len(self._handled_ids()), 0)
        unhandled = [
            r for r in self.store.read_all()
            if r.get("cause") == "model-chain" and not r.get("handled")
        ]
        self.assertEqual(len(unhandled), 2)

    def test_empty_ledger_zero_writeback(self):
        # 账本无目标记录：零写回（mtime 不变）——幂等可重入
        self.stub._maybe_supersede_model_chain_alerts()
        path = self.proot / ".fenix" / "admin_alerts.json"
        self.assertFalse(path.exists())

        self._seed_model_chain()
        self.stub._maybe_supersede_model_chain_alerts()
        mtime1 = path.stat().st_mtime_ns
        self.stub._maybe_supersede_model_chain_alerts()
        self.assertEqual(path.stat().st_mtime_ns, mtime1)

    def test_unknown_cause_records_survive_clean_dispatch(self):
        # unknown 根因记录不参与自动失效（4.4 防呆；即便观测点全通过）
        self.store.append(
            {
                "kind": SIGNAL,
                "signal_type": "verify_regression_missing",
                "spec": "spec-a",
                "severity": "major",
                "description": "d",
                "evidence": "e",
            }
        )
        self.stub._maybe_supersede_model_chain_alerts()
        rec = self.store.read_all()[0]
        self.assertFalse(rec["handled"])


class CauseFieldTest(unittest.TestCase):
    """cause 字段账本增量与产生方注入（tasks 4.1 / 4.6）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.proot = self.tmp / "proj"
        self.proot.mkdir()

    def test_append_persists_cause_and_sanitizes_illegal(self):
        store = AdminStore(self.proot, FakeLogger())
        rec = store.append(
            {
                "kind": SIGNAL,
                "signal_type": "provider_ref_invalid",
                "severity": "major",
                "cause": "model-chain",
                "description": "d",
                "evidence": "e",
            }
        )
        self.assertEqual(rec["cause"], "model-chain")
        bad = store.append(
            {
                "kind": SIGNAL,
                "signal_type": "x",
                "severity": "info",
                "cause": "bogus-cause",
                "description": "d",
                "evidence": "e",
            }
        )
        # 封闭枚举外的非法值归 None（读侧容错 unknown，不臆造枚举值）
        self.assertIsNone(bad["cause"])

    def test_make_signal_injects_cause_from_closed_map(self):
        from test_admin import make_monitor

        _, mon = make_monitor(self.tmp, {})
        sig = mon._make_signal(
            "verify_contract_missing", "spec-a", "d", "e"
        )
        self.assertEqual(sig["cause"], "contract")
        sig = mon._make_signal("daemon_errors", None, "d", "e")
        self.assertEqual(sig["cause"], "daemon-error")
        # 映射外类型 cause=None（读侧容错 unknown）
        sig = mon._make_signal("repeated_failures", "spec-a", "d", "e")
        self.assertIsNone(sig["cause"])
        # 权威映射 sanity：契约族三类型全归 contract
        self.assertEqual(SIGNAL_CAUSE_MAP["verify_contract_redraft"], "contract")
        self.assertEqual(SIGNAL_CAUSE_MAP["verify_regression_missing"], "contract")

    def test_signal_record_passes_cause_through(self):
        from test_admin import make_monitor

        _, mon = make_monitor(self.tmp, {})
        signal = {
            "signal_type": "daemon_errors",
            "spec": None,
            "severity": "major",
            "cause": "daemon-error",
            "description": "d",
            "evidence": "e",
            "recommended_action": "a",
        }
        record = mon._signal_record(signal, escalated=False)
        self.assertEqual(record.get("cause"), "daemon-error")


class CauseBackfillTest(unittest.TestCase):
    """backfill_causes 存量账本回填（task 4.6，daemon 启动首轮一次性）。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.proot = Path(tmp.name) / "proj"
        self.proot.mkdir()
        self.store = AdminStore(self.proot, FakeLogger())

    def _seed(self, signal_type, handled=False, cause=None, note=None):
        rec = self.store.append(
            {
                "kind": SIGNAL,
                "signal_type": signal_type,
                "spec": None,
                "severity": "major",
                "description": "d",
                "evidence": "e",
                **({"cause": cause} if cause else {}),
                **({"resolve_note": note} if note else {}),
            }
        )
        if handled:
            self.store.mark_signal_handled(rec["id"])
        return rec

    def test_backfill_maps_known_types_and_prefixes_notes(self):
        plain = self._seed("verify_contract_missing")
        errs = self._seed("daemon_errors")
        withnote = self._seed("verify_contract_missing", note="先前人工注记")
        done = self._seed("verify_contract_missing", handled=True)  # 已处置不回填
        withcause = self._seed("verify_contract_missing", cause="contract")  # 已有 cause 不动
        self._seed("repeated_failures")  # 映射外不回填（保持无 cause=unknown）

        n = self.store.backfill_causes(SIGNAL_CAUSE_MAP)
        self.assertEqual(n, 3)

        by_id = {r["id"]: r for r in self.store.read_all()}
        got = by_id[plain["id"]]
        self.assertEqual(got["cause"], "contract")
        self.assertIn("存量回填", got["resolve_note"])
        self.assertEqual(by_id[errs["id"]]["cause"], "daemon-error")
        # 已有注记前缀追加（不覆盖人工历史）
        got = by_id[withnote["id"]]
        self.assertEqual(got["cause"], "contract")
        self.assertEqual(got["resolve_note"], "存量回填：先前人工注记")
        # 已处置不旁路改写（handled 历史保持）；已有 cause 不重复回填
        self.assertTrue(by_id[done["id"]]["handled"])
        self.assertIsNone(by_id[done["id"]].get("resolve_note"))
        self.assertEqual(by_id[withcause["id"]]["cause"], "contract")
        self.assertIsNone(by_id[withcause["id"]].get("resolve_note"))
        self.assertFalse(by_id[plain["id"]]["handled"])
        mapped = [r for r in self.store.read_all() if r.get("cause") == "model-chain"]
        self.assertEqual(mapped, [])
        outsider = [
            r for r in self.store.read_all() if r.get("signal_type") == "repeated_failures"
        ][0]
        self.assertIsNone(outsider.get("cause"))

    def test_backfill_is_idempotent(self):
        self._seed("verify_contract_missing")
        self.assertEqual(self.store.backfill_causes(SIGNAL_CAUSE_MAP), 1)
        self.assertEqual(self.store.backfill_causes(SIGNAL_CAUSE_MAP), 0)

    def test_non_dict_mapping_rejected(self):
        self._seed("verify_contract_missing")
        self.assertEqual(self.store.backfill_causes(None), 0)
        self.assertEqual(self.store.backfill_causes("contract"), 0)


class PanelViewTest(unittest.TestCase):
    """面板呈现数据面（task 4.3 后端半边）：resolved 视图扩 superseded 口径。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.proot = Path(tmp.name) / "proj"
        self.proot.mkdir()
        self.store = AdminStore(self.proot, FakeLogger())

    def _seed_signal(self, handled_by=None, fingerprint=None):
        rec = self.store.append(
            {
                "kind": SIGNAL,
                "signal_type": "provider_ref_invalid",
                "spec": None,
                "severity": "major",
                "cause": "model-chain",
                "description": "d",
                "evidence": "e",
                **({"fingerprint": fingerprint} if fingerprint else {}),
            }
        )
        if handled_by == SUPERSEDED_BY:
            self.store.supersede_by_cause("model-chain", "note")
        elif handled_by == AUTO_RESOLVE_BY:
            self.store.auto_resolve_by_type_fingerprint(
                "provider_ref_invalid", set(), "n"
            )
        elif handled_by == "human":
            self.store.mark_signal_handled(rec["id"])
        return rec

    def _resolved_ids(self) -> set:
        from core.dashboard.data.admin_alerts import (
            _resolved_records,
            revert_superseded_alert,
        )

        self._revert_fn = revert_superseded_alert
        records = AdminStore(self.proot, FakeLogger()).read_all()
        return {r["id"] for r in _resolved_records(records)}

    def test_resolved_view_includes_superseded_and_selfheal_signals(self):
        sup = self._seed_signal(handled_by=SUPERSEDED_BY)
        auto = self._seed_signal(fingerprint="implementer:ghost-a")
        self.store.auto_resolve_by_type_fingerprint(
            "provider_ref_invalid", set(), "n"
        )
        got = self._resolved_ids()
        self.assertIn(sup["id"], got)  # 4.3：已失效进已处理折叠区（可纠错可见）
        # auto-resolve 的 signal 不进本视图（5.3 既有口径只认 auto-self-heal，
        # 本任务仅扩 superseded、不扩自动化词表其余成员）
        self.assertNotIn(auto["id"], got)

    def test_resolved_view_still_excludes_manual_and_unhandled_signals(self):
        manual = self._seed_signal(handled_by="human")
        fresh = self._seed_signal()
        got = self._resolved_ids()
        self.assertNotIn(manual["id"], got)  # 人工 mark 的信号不进本视图（既有口径）
        self.assertNotIn(fresh["id"], got)

    def test_revert_alert_data_fn_passthrough(self):
        rec = self._seed_signal(handled_by=SUPERSEDED_BY)
        from core.dashboard.data.admin_alerts import revert_superseded_alert

        self.assertTrue(revert_superseded_alert(self.proot, rec["id"]))
        got = {r["id"]: r for r in AdminStore(self.proot, FakeLogger()).read_all()}
        self.assertFalse(got[rec["id"]]["handled"])
        # 非 superseded 终态不可回退（判定单点在 store）
        done = self.store.append(
            {
                "kind": SIGNAL,
                "signal_type": "x",
                "spec": None,
                "severity": "info",
                "description": "d",
                "evidence": "e",
            }
        )
        self.store.mark_signal_handled(done["id"])
        self.assertFalse(revert_superseded_alert(self.proot, done["id"]))

    def test_revert_supersede_route_registered(self):
        # 撤销端点路由注册（regex 参数化，与 /handled 同款形态）
        from core.dashboard.routes import base as routes_base

        patterns = [p for kind, p, *_ in routes_base._API_POST_ROUTES if kind == "regex"]
        self.assertTrue(
            any("revert-supersede" in p for p in patterns),
            f"revert-supersede 路由未注册: {patterns}",
        )


if __name__ == "__main__":
    unittest.main()

"""
inconclusive 循环升级单元测试（add-verdict-credibility-gate / spec: inconclusive-loop-escalation）

覆盖 tasks 5.1-5.4：
  - 阈值内（1-3 轮）不写 SIGNAL
  - 连续第 N（可配）轮写入 kind=SIGNAL 记录（type=inconclusive_loop）
  - admin_monitor 摄取后唤起 Administrator（STORED_SIGNAL_TYPES 已含 inconclusive_loop）
  - 人工清 _inconclusive_attempts 后从 1 重新计数
  - unfreeze 清 _inconclusive_attempts 同语义
  - SIGNAL 记录含 spec 名、连续轮数、末轮 blocked_env 数
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

# 确保 tests 目录在 import 路径（兼容直接执行）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore, SIGNAL
from core.pm_engine.engine import PMEngine
from core.state_machine import StateMachine


class _FakeLogger:
    def __init__(self):
        self.messages = []

    def _log(self, level, *args):
        self.messages.append((level,) + tuple(str(a) for a in args))

    def info(self, *args):
        self._log("info", *args)

    def warning(self, *args):
        self._log("warning", *args)

    def error(self, *args):
        self._log("error", *args)

    def debug(self, *args):
        self._log("debug", *args)


def _mk_engine(tmpdir, escalate_attempts=4, max_attempts=3):
    """构造 PMEngine 实例（临时 STATE + 真实 StateMachine + AdminStore）。"""
    project_root = Path(tmpdir)
    (project_root / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = _FakeLogger()
    sm = StateMachine(project_root / ".fenix" / "STATE.md", logger)
    config = {"verify_engine": {
        "inconclusive_escalate_attempts": escalate_attempts,
        "inconclusive_max_attempts": max_attempts,
    }}
    engine = PMEngine(sm, mock.MagicMock(), config, project_root, logger)
    sm.add_spec("s1", {"priority": 5})
    sm.update_spec("s1", {"status": "implemented"})
    return engine, sm, logger


def _all_blocked_report(blocked_env=3):
    return {
        "summary": {
            "total": blocked_env, "passed": 0, "warnings": blocked_env,
            "failed": 0, "errors": 0, "blocked_env": blocked_env,
        },
        "scenarios": [
            {"scenario_id": "s-x", "status": "blocked-env",
             "env_probe_detail": "HTTP 探测失联"},
        ],
    }


def _signals(tmpdir):
    """读取 admin store 中的 SIGNAL 记录。"""
    store = AdminStore(Path(tmpdir), _FakeLogger())
    return [r for r in store.read_all() if r.get("kind") == SIGNAL]


class TestEscalationThreshold(unittest.TestCase):
    """Scenario: 连续 blocked-env 达阈值时呼叫 Administrator。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_rounds_1_3_no_signal(self):
        """第 1-3 轮不触发（阈值 4 内不写 SIGNAL）。"""
        engine, sm, _ = _mk_engine(self.tmpdir, escalate_attempts=4)
        report = _all_blocked_report()
        for expected_round in (1, 2, 3):
            handled = engine._verification._handle_env_blocked_inconclusive("s1", report)
            self.assertTrue(handled, f"第 {expected_round} 轮应按 inconclusive 处理")
            self.assertEqual(int(sm.read_one("s1")["_inconclusive_attempts"]),
                             expected_round)
            sigs = _signals(self.tmpdir)
            inconclusive = [s for s in sigs
                            if s.get("signal_type") == "inconclusive_loop"]
            self.assertEqual(len(inconclusive), 0,
                             f"第 {expected_round} 轮不应写入 inconclusive_loop SIGNAL")

    def test_round_4_writes_signal(self):
        """第 4 轮（缺省阈值）写入 SIGNAL 且暂停自动重验。"""
        engine, sm, _ = _mk_engine(self.tmpdir, escalate_attempts=4, max_attempts=10)
        report = _all_blocked_report(blocked_env=3)
        for _ in range(3):
            engine._verification._handle_env_blocked_inconclusive("s1", report)
        handled = engine._verification._handle_env_blocked_inconclusive("s1", report)
        self.assertTrue(handled)
        sigs = _signals(self.tmpdir)
        inconclusive = [s for s in sigs
                        if s.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(inconclusive), 1, "第 4 轮应写入一条 inconclusive_loop SIGNAL")
        rec = inconclusive[0]
        self.assertIn("s1", str(rec.get("spec")))
        self.assertIn("连续轮数=4", rec.get("evidence") or "")
        self.assertIn("末轮blocked_env数=3", rec.get("evidence") or "")
        self.assertIn("HTTP 探测失联", rec.get("evidence") or "")

    def test_threshold_configurable_n(self):
        """阈值可配：N=2 时第 2 轮触发 SIGNAL。"""
        engine, sm, _ = _mk_engine(self.tmpdir, escalate_attempts=2, max_attempts=5)
        report = _all_blocked_report()
        # 第 1 轮：不触发
        engine._verification._handle_env_blocked_inconclusive("s1", report)
        inconclusive = [s for s in _signals(self.tmpdir)
                        if s.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(inconclusive), 0, "第 1 轮不应触发")
        # 第 2 轮：触发
        engine._verification._handle_env_blocked_inconclusive("s1", report)
        inconclusive = [s for s in _signals(self.tmpdir)
                        if s.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(inconclusive), 1, "第 2 轮应触发 SIGNAL")

    def test_judge_env_declared_writes_signal(self):
        """judge 自述环境暂停分支同样达阈值写 SIGNAL。"""
        engine, sm, _ = _mk_engine(self.tmpdir, escalate_attempts=2, max_attempts=5)
        for _ in range(2):
            engine._verification._handle_judge_env_declared("s1")
        inconclusive = [s for s in _signals(self.tmpdir)
                        if s.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(inconclusive), 1)


class TestManualCountReset(unittest.TestCase):
    """Scenario: 人工清计数后从 1 重新计数。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_clear_count_restarts_from_1(self):
        """人工清 _inconclusive_attempts 后，后续 blocked-env 从 1 重新计数。"""
        engine, sm, _ = _mk_engine(self.tmpdir, escalate_attempts=5, max_attempts=10)
        report = _all_blocked_report()
        # 先累积 3 轮
        for _ in range(3):
            engine._verification._handle_env_blocked_inconclusive("s1", report)
        self.assertEqual(int(sm.read_one("s1")["_inconclusive_attempts"]), 3)
        # 人工处置：清计数
        sm.update_spec("s1", {"_inconclusive_attempts": 0})
        # 新一轮从 1 重新计数
        engine._verification._handle_env_blocked_inconclusive("s1", report)
        self.assertEqual(int(sm.read_one("s1")["_inconclusive_attempts"]), 1)
        # 且不会因为旧残留计数立即触发升级
        inconclusive = [s for s in _signals(self.tmpdir)
                        if s.get("signal_type") == "inconclusive_loop"]
        self.assertEqual(len(inconclusive), 0)

    def test_unfreeze_clears_count(self):
        """unfreeze 清 _inconclusive_attempts（与 _verify_redo_count 同语义）。"""
        engine, sm, _ = _mk_engine(self.tmpdir, escalate_attempts=10, max_attempts=10)
        report = _all_blocked_report()
        for _ in range(3):
            engine._verification._handle_env_blocked_inconclusive("s1", report)
        self.assertEqual(int(sm.read_one("s1")["_inconclusive_attempts"]), 3)
        # 冻结后解冻
        sm.update_spec("s1", {"status": "blocked"})
        sm.freeze_spec("s1")
        sm.unfreeze_spec("s1", status="implemented")
        self.assertEqual(int(sm.read_one("s1")["_inconclusive_attempts"]), 0,
                         "unfreeze 后 _inconclusive_attempts 应清零")
        # 新一轮从 1 计数
        engine._verification._handle_env_blocked_inconclusive("s1", report)
        self.assertEqual(int(sm.read_one("s1")["_inconclusive_attempts"]), 1)


from core.admin_monitor import AdminMonitor, STORED_SIGNAL_TYPES


class _MonitorSM:
    """AdminMonitor 测试用最小 StateMachine 替身。"""

    def __init__(self, statuses: dict):
        self.statuses = statuses

    def read_one(self, spec):
        return {"status": self.statuses.get(spec, "")}


class _MinimalStore:
    """AdminStore 轻量替身：记录 append/mark_escalated 调用（mark 会改写记录）。"""

    def __init__(self):
        self.records = []
        self.escalated = []

    def read_all(self):
        return list(self.records)

    def append(self, entry: dict) -> dict:
        entry["id"] = f"rec-{len(self.records)}"
        self.records.append(entry)
        return dict(entry)

    def mark_escalated(self, alert_id: str) -> bool:
        self.escalated.append(alert_id)
        for rec in self.records:
            if rec.get("id") == alert_id:
                rec["escalated"] = True
                return True
        return False


class TestAdminMonitorIngestion(unittest.TestCase):
    """Scenario: admin_monitor 摄取 inconclusive_loop SIGNAL 后唤起 Administrator。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir(parents=True, exist_ok=True)
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)
        self.store = _MinimalStore()
        self.sm = _MonitorSM({"s1": "implemented"})
        self.logger = _FakeLogger()
        # 注入一条待唤起的 inconclusive_loop SIGNAL
        self.store.append({
            "kind": SIGNAL, "signal_type": "inconclusive_loop", "spec": "s1",
            "severity": "major",
            "description": "连续 4 轮 blocked-env",
            "evidence": "spec=s1; 连续轮数=4; 末轮blocked_env数=3",
            "recommended_action": "环境核查",
        })
        self.mon = AdminMonitor(
            {}, self.sm, self.proot, self.logger,
            store=self.store,
            agent_runner=mock.MagicMock(),
        )

    def test_inconclusive_loop_in_stored_types(self):
        self.assertIn("inconclusive_loop", STORED_SIGNAL_TYPES)

    def test_detect_ingests_inconclusive_loop_and_invokes(self):
        with mock.patch.object(self.mon, "_invoke_administrator",
                               return_value=None) as mock_invoke:
            raw = self.mon._detect_family_explosion()
            self.assertEqual(len(raw), 1, "应摄取到 inconclusive_loop 信号")
            self.assertEqual(raw[0]["signal_type"], "inconclusive_loop")
            self.assertEqual(raw[0]["spec"], "s1")
            # 记录被标记 escalated
            self.assertEqual(len(self.store.escalated), 1)
            # 唤起 Administrator（_invoke_administrator 被调用一次）
            self.assertEqual(mock_invoke.call_count, 1)
        # 二次摄取不重复（已 escalated）
        again = self.mon._detect_family_explosion()
        self.assertEqual(len(again), 0)

    def test_suggestion_includes_env_checklist(self):
        from core.admin_monitor import SIGNAL_RECOMMENDATION
        self.assertIn("验证环境核查清单",
                      SIGNAL_RECOMMENDATION.get("inconclusive_loop", ""))
        self.assertIn("解冻", SIGNAL_RECOMMENDATION.get("inconclusive_loop", ""))
        self.assertIn("_inconclusive_attempts",
                      SIGNAL_RECOMMENDATION.get("inconclusive_loop", ""))


class TestVerifyUniformFailureIngestion(unittest.TestCase):
    """Scenario: admin_monitor 摄取 verify_uniform_failure SIGNAL 后唤起 Administrator。

    fix-verify-uniform-failure-consumer 回归：全场景同因失败哨写入的
    verify_uniform_failure 此前不在 STORED_SIGNAL_TYPES 白名单，记录落 store
    后无人摄取——文案自称「已呼叫 admin 介入判断」却从不唤起（2026-09-14
    evo-planner-scenario-schema-alignment 两轮 13/13 同因失败悬置十余小时实证）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir(parents=True, exist_ok=True)
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)
        self.store = _MinimalStore()
        self.sm = _MonitorSM({"s1": "testing"})
        self.logger = _FakeLogger()
        self.store.append({
            "kind": SIGNAL, "signal_type": "verify_uniform_failure", "spec": "s1",
            "severity": "major",
            "description": "全场景同因失败（13/13，签名一致: \"\"）——疑似环境或场景问题",
            "evidence": "signature=; failed=13",
            "recommended_action": "判断失败类别",
        })
        self.mon = AdminMonitor(
            {}, self.sm, self.proot, self.logger,
            store=self.store,
            agent_runner=mock.MagicMock(),
        )

    def test_uniform_failure_in_stored_types(self):
        self.assertIn("verify_uniform_failure", STORED_SIGNAL_TYPES)

    def test_detect_ingests_uniform_failure_and_invokes(self):
        with mock.patch.object(self.mon, "_invoke_administrator",
                               return_value=None) as mock_invoke:
            raw = self.mon._detect_family_explosion()
            self.assertEqual(len(raw), 1, "应摄取到 verify_uniform_failure 信号")
            self.assertEqual(raw[0]["signal_type"], "verify_uniform_failure")
            self.assertEqual(raw[0]["spec"], "s1")
            self.assertEqual(len(self.store.escalated), 1)
            self.assertEqual(mock_invoke.call_count, 1)
        # 二次摄取不重复（已 escalated）
        again = self.mon._detect_family_explosion()
        self.assertEqual(len(again), 0)

    def test_severity_and_suggestion_registered(self):
        from core.admin_monitor import SIGNAL_SEVERITY, SIGNAL_RECOMMENDATION
        self.assertEqual(SIGNAL_SEVERITY.get("verify_uniform_failure"), "major")
        rec = SIGNAL_RECOMMENDATION.get("verify_uniform_failure", "")
        self.assertIn("判类别", rec)
        self.assertIn("report.json", rec)

    def test_terminal_spec_skips_invocation(self):
        """终态 spec（done/pushed）不唤起——同因失败困境实质已消失。"""
        self.sm.statuses["s1"] = "pushed"
        with mock.patch.object(self.mon, "_invoke_administrator",
                               return_value=None) as mock_invoke:
            raw = self.mon._detect_family_explosion()
            self.assertEqual(raw, [])
            self.assertEqual(mock_invoke.call_count, 0)


class TestDispatchStalledStaleSnapshotGuard(unittest.TestCase):
    """Scenario: dispatch_stalled 记录被摄取前复核「ready 滞留」前提是否仍成立。

    2026-09-17 事故：'evo-orphaned-state-probe-calibration' 的 dispatch_stalled
    记录写于 18:25:31Z（队列老化窗口内的假就绪滞留误报），spec 已于 19:52:22Z
    被正常派发，20:16:20Z 该积压记录才被摄取兑现（此时 implementer run 正在
    产流），20:26:00Z run 成功收工——唤起时刻前提已被事实推翻 24 分钟。

    守卫口径：dispatch_stalled 的困境前提 = spec 处于 ready。摄取时 spec 当前
    状态已非 ready → 标记 escalated 核销跳过，不唤起 Administrator。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir(parents=True, exist_ok=True)
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)
        self.store = _MinimalStore()
        self.sm = _MonitorSM({"s1": "ready"})
        self.logger = _FakeLogger()
        self.store.append({
            "kind": SIGNAL, "signal_type": "dispatch_stalled", "spec": "s1",
            "severity": "major",
            "description": "'s1' 长期滞留 ready 且派发未成立（处置方向见 evidence）",
            "evidence": "ready stall 916m without dispatch activity; error=No error recorded",
            "recommended_action": "先按 evidence 判来源",
        })
        self.mon = AdminMonitor(
            {}, self.sm, self.proot, self.logger,
            store=self.store,
            agent_runner=mock.MagicMock(),
        )

    def test_stale_record_after_dispatch_is_not_ingested(self):
        """前提被推翻（spec 已非 ready）→ 不唤起，记录被核销。"""
        self.sm.statuses["s1"] = "implementing"  # 已被正常派发
        with mock.patch.object(self.mon, "_invoke_administrator",
                               return_value=None) as mock_invoke:
            raw = self.mon._detect_family_explosion()
            self.assertEqual(raw, [], "陈旧快照不应转化为信号")
            self.assertEqual(mock_invoke.call_count, 0, "不应唤起 Administrator")
        # 记录被标记 escalated 核销（保留可审计，下一 tick 不再重捞）
        self.assertEqual(self.store.escalated, ["rec-0"])
        again = self.mon._detect_family_explosion()
        self.assertEqual(len(again), 0)

    def test_genuine_ready_stall_still_ingested(self):
        """前提仍成立（spec 仍 ready）→ 照常唤起（不掩真阳性）。"""
        with mock.patch.object(self.mon, "_invoke_administrator",
                               return_value=None) as mock_invoke:
            raw = self.mon._detect_family_explosion()
            self.assertEqual(len(raw), 1, "真实 ready 滞留应照常上报")
            self.assertEqual(raw[0]["spec"], "s1")
            self.assertEqual(mock_invoke.call_count, 1)

    def test_terminal_status_still_covered_by_terminal_guard(self):
        """终态 spec 走既有终态守卫（两条守卫互不冲突）。"""
        self.sm.statuses["s1"] = "pushed"
        with mock.patch.object(self.mon, "_invoke_administrator",
                               return_value=None) as mock_invoke:
            raw = self.mon._detect_family_explosion()
            self.assertEqual(raw, [])
            self.assertEqual(mock_invoke.call_count, 0)

    def test_other_signal_types_are_not_premise_filtered(self):
        """守卫只作用于 dispatch_stalled：其余信号的困境前提与 ready 无关。"""
        from core.admin_monitor import _STALL_PREMISE_SIGNAL_TYPES
        self.assertEqual(_STALL_PREMISE_SIGNAL_TYPES, ("dispatch_stalled",))
        # testing 态的 inconclusive_loop 在其自身场景下（TestAdminMonitorIngestion
        # 的 s1=implemented）照常摄取——此处同表锁死豁免范围
        self.store.append({
            "kind": SIGNAL, "signal_type": "inconclusive_loop", "spec": "s1",
            "severity": "major", "description": "连续 4 轮 blocked-env",
            "evidence": "spec=s1; 连续轮数=4", "recommended_action": "环境核查",
        })
        self.sm.statuses["s1"] = "testing"
        with mock.patch.object(self.mon, "_invoke_administrator",
                               return_value=None) as mock_invoke:
            raw = self.mon._detect_family_explosion()
            self.assertEqual([s["signal_type"] for s in raw], ["inconclusive_loop"])
            self.assertEqual(mock_invoke.call_count, 1)

    def test_missing_status_fails_open(self):
        """status 缺失（前提不可推翻）→ fail-open 照常摄取，不掩真阳性。"""
        self.sm.statuses.pop("s1", None)
        with mock.patch.object(self.mon, "_invoke_administrator",
                               return_value=None) as mock_invoke:
            raw = self.mon._detect_family_explosion()
            self.assertEqual(len(raw), 1, "status 缺失时不得误判前提被推翻")
            self.assertEqual(mock_invoke.call_count, 1)

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


if __name__ == "__main__":
    unittest.main()
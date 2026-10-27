"""
fix-scheduled-reverify-survive-restart 回归测试。

覆盖（specs/scheduled-reverify-restart-durability）：
- 排程重验状态持久化：`_schedule_scenario_repair_reverify` 把来源标记
  （_reverify_pending/_reverify_reason）与截止字段（_dispatch_backoff_until）
  同一原子写落 STATE；截止单源复用 _dispatch_backoff_until。
- 清零接线三处：重验执行落定（verified/bug-found）+ 人工解冻（unfreeze_spec）
  + 恢复路径拾起（recover_interrupted 到期分支）——三字段同步清零。
- 恢复路径识别排程等待态：daemon 全扫恢复 TESTING 分支以 _reverify_pending
  标记为门（MUST NOT 裸读多机制共用的 _dispatch_backoff_until）：
  ①未到期 → 保持 testing 不重置、字段保留；②已到期 → 保持 testing、清标记、
  周期扫描可拾起；③无排程真孤儿态 → 既有重置行为逐位不变；
  ④排程字段在非 testing 态 → 不影响其他状态机转换；
  ⑤非排程退避等待（锁冲突 backoff）→ 既有重置行为不变（标记为门的回归证明）。
"""
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import (
    REVERIFY_PENDING_FIELD,
    REVERIFY_REASON_FIELD,
    REVERIFY_STATE_RESET_FIELDS,
    StateMachine,
)


def _push_spec_to(sm: StateMachine, name: str, target: str):
    """把 spec 沿合法链走到 target（test_daemon_lifecycle_races 同款）。"""
    chain = {
        "implementing": ["drafted", "ready", "implementing"],
        "testing": ["drafted", "ready", "implementing", "implemented", "testing"],
    }
    for step in chain[target]:
        sm.update_spec(name, {"status": step})


def _set_reverify(sm: StateMachine, name: str, until_offset: float,
                  reason: str = "scenario_repair_exhausted"):
    """给 spec 写入排程重验等待态三字段（until_offset 为相对当前的秒数）。"""
    sm.update_spec(name, {
        "_dispatch_backoff_until": int(time.time() + until_offset),
        REVERIFY_PENDING_FIELD: True,
        REVERIFY_REASON_FIELD: reason,
    })


def _pending(entry: dict) -> bool:
    """读侧布尔归一防御（STATE.md 往返安全，与生产读侧同口径）。"""
    return bool(entry.get(REVERIFY_PENDING_FIELD))


class TestScheduleStatePersistence(unittest.TestCase):
    """排程重验状态持久化（tasks 1.1/1.2）。

    排程后 STATE 条目含 `_reverify_pending`/`_reverify_reason` 且
    `_dispatch_backoff_until` 同一原子写；verified/bug-found 落定与人工解冻
    后三字段清零。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)
        self.sm.add_spec("demo-spec", {"priority": 5})
        _push_spec_to(self.sm, "demo-spec", "testing")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_pipe(self):
        """构造最小 VerificationPipeline 桩（test_pm_verification 同款）。"""
        from core.pm_engine.verification import VerificationPipeline
        pm = SimpleNamespace()
        pm.project_root = Path(self.tmpdir)
        pm.logger = MagicMock()
        pm.state_machine = self.sm
        pm.agent_runner = MagicMock()
        pm._send_human_escalation_alert = MagicMock()
        pm._enqueue = MagicMock()
        pm._process_queue = MagicMock()
        return VerificationPipeline(pm)

    def test_schedule_writes_three_fields_same_atomic_write(self):
        """排程写点：来源标记与截止字段同一原子写（单次 update_spec 携带三键）。"""
        from core.pm_engine.verification.escalation import (
            _schedule_scenario_repair_reverify,
        )
        pipe = self._make_pipe()
        calls = []
        orig = self.sm.update_spec

        def spy(name, updates, **kw):
            calls.append(dict(updates))
            return orig(name, updates, **kw)

        self.sm.update_spec = spy
        try:
            with patch(
                "core.pm_engine.verification.escalation.threading.Timer"
            ) as timer_cls:
                _schedule_scenario_repair_reverify(pipe, "demo-spec")
        finally:
            self.sm.update_spec = orig
        self.assertEqual(timer_cls.call_count, 1)
        # 同一原子写：恰好一次 update_spec 调用同时携带三键
        carrying = [
            c for c in calls
            if "_dispatch_backoff_until" in c
            and REVERIFY_PENDING_FIELD in c
            and REVERIFY_REASON_FIELD in c
        ]
        self.assertEqual(len(carrying), 1,
                         f"三字段必须同一原子写落盘，实际调用: {calls}")
        self.assertTrue(carrying[0][REVERIFY_PENDING_FIELD])
        self.assertEqual(carrying[0][REVERIFY_REASON_FIELD],
                         "scenario_repair_exhausted")
        self.assertGreater(int(carrying[0]["_dispatch_backoff_until"]),
                           int(time.time()))
        # STATE 往返后可读出（daemon 重启后新实例可读）
        sm2 = StateMachine(self.state_path, self.logger)
        entry = sm2.read_one("demo-spec")
        self.assertTrue(_pending(entry))
        self.assertEqual(entry.get(REVERIFY_REASON_FIELD),
                         "scenario_repair_exhausted")
        self.assertGreater(int(entry.get("_dispatch_backoff_until") or 0),
                           int(time.time()))

    def test_first_exhaustion_writes_markers_via_pipeline(self):
        """首次耗尽全路径：计数 1 + 三字段落 STATE + 保持 testing。"""
        from core.pm_engine.verification import _SCENARIO_REPAIR_MAX_ROUNDS
        pipe = self._make_pipe()
        self.assertTrue(pipe._handle_scenario_repaired(
            "demo-spec", "scenario-repaired", _SCENARIO_REPAIR_MAX_ROUNDS))
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertEqual(
            int(entry.get("_scenario_repair_exhausted_rounds") or 0), 1)
        self.assertTrue(_pending(entry))
        self.assertEqual(entry.get(REVERIFY_REASON_FIELD),
                         "scenario_repair_exhausted")
        self.assertGreater(int(entry.get("_dispatch_backoff_until") or 0),
                           int(time.time()))

    def test_verified_landing_clears_fields(self):
        """verified 落定（重验执行落定清零点①）：三字段清零。"""
        from core.pm_engine.verification.verdict_evidence import (
            _record_verdict_adoption,
        )
        pipe = self._make_pipe()
        _set_reverify(self.sm, "demo-spec", 900)
        with patch("core.verify_report.record_verdict_round"), \
                patch("core.verify_report.verdict_failed_ids",
                      return_value=[]), \
                patch("core.verify_report._sum_verify_chain_tokens",
                      return_value=None):
            _record_verdict_adoption(pipe, "demo-spec", "verified", report={})
        entry = self.sm.read_one("demo-spec")
        self.assertFalse(_pending(entry))
        self.assertFalse(entry.get(REVERIFY_REASON_FIELD))
        self.assertFalse(entry.get("_dispatch_backoff_until"))

    def test_bug_found_landing_clears_fields(self):
        """bug-found 落定（重验执行落定清零点①）：三字段清零。"""
        from core.pm_engine.verification.verdict_evidence import (
            _record_verdict_adoption,
        )
        pipe = self._make_pipe()
        _set_reverify(self.sm, "demo-spec", 900)
        with patch("core.verify_report.record_verdict_round"), \
                patch("core.verify_report.verdict_failed_ids",
                      return_value=[]), \
                patch("core.verify_report._sum_verify_chain_tokens",
                      return_value=None):
            _record_verdict_adoption(pipe, "demo-spec", "bug-found",
                                     report={"failed": []})
        entry = self.sm.read_one("demo-spec")
        self.assertFalse(_pending(entry))
        self.assertFalse(entry.get(REVERIFY_REASON_FIELD))
        self.assertFalse(entry.get("_dispatch_backoff_until"))

    def test_unfreeze_clears_fields(self):
        """人工解冻（清零点②，unfreeze_spec 清零集同一原子写）：三字段清零。"""
        _set_reverify(self.sm, "demo-spec", 900)
        self.sm.freeze_for_human(
            "demo-spec",
            error="FROZEN 原状态 testing · 等待人工裁决",
            signal_type="verify_redo_exhausted",
            severity="major",
            description="demo",
            evidence="spec=demo-spec",
            recommended_action="unfreeze_spec 解冻",
        )
        self.sm.unfreeze_spec("demo-spec", status="testing")
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "testing")
        self.assertFalse(_pending(entry))
        self.assertFalse(entry.get(REVERIFY_REASON_FIELD))
        self.assertFalse(entry.get("_dispatch_backoff_until"))

    def test_reset_fields_cover_all_three(self):
        """清零集单点：REVERIFY_STATE_RESET_FIELDS 恰含三字段（防漂移锚）。"""
        self.assertEqual(
            set(REVERIFY_STATE_RESET_FIELDS),
            {REVERIFY_PENDING_FIELD, REVERIFY_REASON_FIELD,
             "_dispatch_backoff_until"},
        )
        self.assertFalse(REVERIFY_STATE_RESET_FIELDS[REVERIFY_PENDING_FIELD])
        self.assertIsNone(REVERIFY_STATE_RESET_FIELDS[REVERIFY_REASON_FIELD])
        self.assertIsNone(REVERIFY_STATE_RESET_FIELDS["_dispatch_backoff_until"])


class TestRecoveryRespectsReverifyWait(unittest.TestCase):
    """恢复路径识别排程等待态（tasks 2.1/2.2）。

    daemon 全扫恢复 TESTING 分支以 `_reverify_pending` 标记为门的五场景。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        (Path(self.tmpdir) / ".fenix").mkdir(parents=True, exist_ok=True)
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.logger = MagicMock()
        self.sm = StateMachine(self.state_path, self.logger)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _redo_count(self, entry):
        return int(entry.get("_verify_redo_count") or 0)

    def test_unexpired_reverify_wait_not_reset(self):
        """①testing + 未到期排程 + 无在飞 run → 恢复不重置、字段保留。"""
        self.sm.add_spec("spec-a", {"status": "testing"})
        _set_reverify(self.sm, "spec-a", 900)
        recovered = self.sm.recover_interrupted()
        self.assertNotIn("spec-a", recovered)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "testing")
        # 排程字段原样保留（到点由周期扫描触发重验）
        self.assertTrue(_pending(entry))
        self.assertEqual(entry.get(REVERIFY_REASON_FIELD),
                         "scenario_repair_exhausted")
        self.assertGreater(int(entry.get("_dispatch_backoff_until") or 0),
                           int(time.time()))
        # 未走孤儿态重置：重启重验计数不递增、无恢复文案
        self.assertEqual(self._redo_count(entry), 0)
        self.assertNotIn("Recovered from interrupted state",
                         str(entry.get("error") or ""))

    def test_expired_reverify_pickup(self):
        """②testing + 已到期排程 → 恢复不重置、标记清除、周期扫描可拾起。"""
        from core.admin_monitor import spec_is_undriven

        self.sm.add_spec("spec-a", {"status": "testing"})
        _set_reverify(self.sm, "spec-a", 900)
        # 对照：未到期窗口内探测器静默（spec_is_undriven 条件③）
        entry = self.sm.read_one("spec-a")
        self.assertFalse(
            spec_is_undriven(Path(self.tmpdir), "spec-a", entry),
            "退避窗内 spec_is_undriven 条件③应判有意等待",
        )
        # 排程到期（重启恰落在到期窗口）
        self.sm.update_spec(
            "spec-a",
            {"_dispatch_backoff_until": int(time.time()) - 10},
        )
        recovered = self.sm.recover_interrupted()
        # 不重置：不进 recovered（recovered 只收「确实恢复了状态」的 spec）
        self.assertNotIn("spec-a", recovered)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "testing")
        self.assertEqual(self._redo_count(entry), 0)
        # 标记与截止残留已清（恢复路径拾起清零点③）
        self.assertFalse(_pending(entry))
        self.assertFalse(entry.get(REVERIFY_REASON_FIELD))
        self.assertFalse(entry.get("_dispatch_backoff_until"))
        # 周期扫描可拾起：出窗后 spec_is_undriven 判无驱动
        self.assertTrue(
            spec_is_undriven(Path(self.tmpdir), "spec-a", entry),
            "到期清标记后 event_bus._recover_testing 周期扫描应可拾起",
        )

    def test_true_orphan_unchanged(self):
        """③testing 无排程无在飞 → 既有重置行为不变（逐位兼容）。"""
        self.sm.add_spec("spec-a", {"status": "testing"})
        recovered = self.sm.recover_interrupted()
        self.assertIn("spec-a", recovered)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "implemented")
        self.assertIn("Recovered from interrupted state: testing",
                      str(entry.get("error") or ""))
        self.assertEqual(self._redo_count(entry), 1)

    def test_fields_on_non_testing_no_effect(self):
        """④排程字段存在但 spec 非 testing → 不影响其他状态机转换。"""
        # implementing 态：既有恢复行为不受排程字段影响（重置 ready）
        self.sm.add_spec("spec-b", {"status": "implementing"})
        _set_reverify(self.sm, "spec-b", 900)
        recovered = self.sm.recover_interrupted()
        self.assertIn("spec-b", recovered)
        entry = self.sm.read_one("spec-b")
        self.assertEqual(entry["status"], "ready")
        self.assertIn("Recovered from interrupted state: implementing",
                      str(entry.get("error") or ""))
        # 正常转换链不受排程字段影响：testing 态可正常流转 bug-found
        self.sm.add_spec("spec-c", {"status": "testing"})
        _set_reverify(self.sm, "spec-c", 900)
        self.assertTrue(self.sm.transition("spec-c", "bug-found"))
        self.assertEqual(self.sm.read_one("spec-c")["status"], "bug-found")

    def test_non_reverify_backoff_still_reset(self):
        """⑤testing + 非排程退避等待（锁冲突 backoff）无在飞 → 既有重置不变。

        标记为门的回归证明：裸读 `_dispatch_backoff_until` 会把本场景误豁免
        （design D2 明令禁止）；以 `_reverify_pending` 为门则照常重置。
        """
        self.sm.add_spec("spec-a", {"status": "testing"})
        # 只写退避截止，不写排程标记（锁冲突/instant-fail 退避写点形态）
        self.sm.update_spec(
            "spec-a",
            {"_dispatch_backoff_until": int(time.time()) + 900},
        )
        recovered = self.sm.recover_interrupted()
        self.assertIn("spec-a", recovered)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "implemented")
        self.assertIn("Recovered from interrupted state: testing",
                      str(entry.get("error") or ""))

    def test_corrupted_deadline_treated_as_expired(self):
        """排程标记在、截止缺失/不可解析 → 视同已到期：清标记交周期扫描。

        等待一个不可判定的截止会让 testing 悬挂；fail-open 到「拾起」路径。
        """
        self.sm.add_spec("spec-a", {"status": "testing"})
        self.sm.update_spec(
            "spec-a",
            {
                "_dispatch_backoff_until": "not-a-number",
                REVERIFY_PENDING_FIELD: True,
                REVERIFY_REASON_FIELD: "scenario_repair_exhausted",
            },
        )
        recovered = self.sm.recover_interrupted()
        self.assertNotIn("spec-a", recovered)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "testing")
        self.assertFalse(_pending(entry))
        self.assertFalse(entry.get("_dispatch_backoff_until"))


if __name__ == "__main__":
    unittest.main()

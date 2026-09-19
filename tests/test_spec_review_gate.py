"""tests for spec-review-gate skip whitelist and transition validation.

Covers:
- Skip whitelist: all 4 criteria must match to skip; evo- hard veto
- Conservative: missing mode / missing deliverables → does not skip
- never mode: all channels go straight to ready
- reviewing transitions valid/invalid
"""

import json
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import (
    StateMachine, SpecStatus, VALID_TRANSITIONS,
    FROZEN_FIELD, parse_orig_status,
)
from core.pm_engine.promotion import should_skip_review
from core.pm_engine.spec_review import SpecReviewManager, MAX_REVIEW_ATTEMPTS, MAX_REJECT_REDO
from core.agent_runner.prompt_builder import spec_review_result_path
from core.admin_monitor import AdminMonitor
from core.admin_store import AdminStore, ESCALATION


def _mk_spec_dir(proot: Path, name: str, mode="fast-track", cap_dirs=1,
                 deliverables=2, is_evo=False) -> Path:
    """Create a spec dir with controllable mode / capability dirs / deliverables count."""
    name = f"evo-{name}" if is_evo else name
    d = proot / "spec" / "changes" / name
    d.mkdir(parents=True, exist_ok=True)
    # .spec.yaml
    (d / ".spec.yaml").write_text(f"mode: {mode}\n", encoding="utf-8")
    # capabilities
    if cap_dirs >= 0:
        specs_dir = d / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        for i in range(cap_dirs):
            (specs_dir / f"cap{i}").mkdir()
    # tasks.md with deliverables count
    entries = "\n".join(
        f"- path: core/file{i}.py\n  kind: modify\n" for i in range(deliverables)
    ) if deliverables >= 0 else ""
    (d / "tasks.md").write_text(
        f"# Tasks\n\n## Deliverables\n\n```yaml\n{entries}```\n\n## 1. x\n\n- [ ] 1.1 do it\n",
        encoding="utf-8",
    )
    return d


class TestSkipWhitelist(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _cfg(self, mode="auto"):
        return {"gates": {"promote_mode": "auto", "spec_review_mode": mode}}

    def test_all_four_match_skips(self):
        """fast-track + 1 cap + <=3 deliverables + non-evo → skip."""
        _mk_spec_dir(self.proot, "simple", cap_dirs=1, deliverables=2)
        self.assertTrue(should_skip_review(self.proot, "simple", self._cfg(), MagicMock()))

    def test_evo_hard_veto(self):
        """evo- prefix → never skip even if all other criteria match."""
        _mk_spec_dir(self.proot, "evo-simple", cap_dirs=1, deliverables=2, is_evo=True)
        self.assertFalse(should_skip_review(self.proot, "evo-simple", self._cfg(), MagicMock()))

    def test_non_fast_track_no_skip(self):
        """mode=full → not skipped."""
        _mk_spec_dir(self.proot, "fullspec", mode="full", cap_dirs=1, deliverables=2)
        self.assertFalse(should_skip_review(self.proot, "fullspec", self._cfg(), MagicMock()))

    def test_cap_count_over_threshold_no_skip(self):
        """2 capability dirs → not skipped."""
        _mk_spec_dir(self.proot, "multicap", cap_dirs=2, deliverables=2)
        self.assertFalse(should_skip_review(self.proot, "multicap", self._cfg(), MagicMock()))

    def test_deliverables_over_threshold_no_skip(self):
        """4 deliverables → not skipped."""
        _mk_spec_dir(self.proot, "bigdeliv", cap_dirs=1, deliverables=4)
        self.assertFalse(should_skip_review(self.proot, "bigdeliv", self._cfg(), MagicMock()))

    def test_missing_mode_conservative_no_skip(self):
        """No mode field → not skipped."""
        d = self.proot / "spec" / "changes" / "nomode"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".spec.yaml").write_text("name: x\n", encoding="utf-8")
        (d / "tasks.md").write_text("# Tasks\n- [ ] 1.1 do it\n", encoding="utf-8")
        self.assertFalse(should_skip_review(self.proot, "nomode", self._cfg(), MagicMock()))

    def test_missing_deliverables_conservative_no_skip(self):
        """No Deliverables section → not skipped."""
        d = self.proot / "spec" / "changes" / "nodecl"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".spec.yaml").write_text("mode: fast-track\n", encoding="utf-8")
        (d / "tasks.md").write_text("# Tasks\n- [ ] 1.1 do it\n", encoding="utf-8")
        self.assertFalse(should_skip_review(self.proot, "nodecl", self._cfg(), MagicMock()))

    def test_never_mode_always_skip(self):
        """spec_review_mode=never → skip regardless of criteria."""
        _mk_spec_dir(self.proot, "evo-never", cap_dirs=5, deliverables=10, is_evo=True)
        self.assertTrue(should_skip_review(self.proot, "evo-never", {"gates": {"spec_review_mode": "never"}}, MagicMock()))


class TestReviewingTransitions(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, MagicMock())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _add(self, name="spec", status="drafted"):
        self.sm.add_spec(name, {"status": status})
        return name

    def test_drafted_can_enter_reviewing(self):
        self._add()
        self.assertTrue(self.sm.transition("spec", "reviewing"))
        self.assertEqual(self.sm.read_one("spec")["status"], "reviewing")

    def test_reviewing_to_ready(self):
        self._add()
        self.sm.transition("spec", "reviewing")
        self.assertTrue(self.sm.transition("spec", "ready"))

    def test_reviewing_to_blocked(self):
        self._add()
        self.sm.transition("spec", "reviewing")
        self.assertTrue(self.sm.transition("spec", "blocked"))

    def test_blocked_to_reviewing(self):
        self._add()
        self.sm.transition("spec", "reviewing")
        self.sm.transition("spec", "blocked")
        self.assertTrue(self.sm.transition("spec", "reviewing"))

    def test_illegal_transition_rejected(self):
        """reviewing → implementing is illegal and keeps state."""
        self._add()
        self.sm.transition("spec", "reviewing")
        self.assertFalse(self.sm.transition("spec", "implementing"))
        self.assertEqual(self.sm.read_one("spec")["status"], "reviewing")

    def test_all_statuses_contains_reviewing(self):
        self.assertIn(SpecStatus.REVIEWING, SpecStatus.ALL)
        self.assertEqual(len(SpecStatus.ALL), 11)

    def test_gate_transitions_excludes_reviewing(self):
        """Gate escape-hatch MUST NOT include reviewing."""
        from core.state_machine import GATE_TRANSITIONS
        for targets in GATE_TRANSITIONS.values():
            self.assertNotIn(SpecStatus.REVIEWING, targets)

    def test_interrupted_includes_reviewing(self):
        from core.state_machine import INTERRUPTED_STATES
        self.assertIn(SpecStatus.REVIEWING, INTERRUPTED_STATES)


class _FakeRunner:
    """Minimal agent_runner stub exposing hard-gate API and result consumption.

    gate_err=None 时结果硬门通过（返回 None）；run_spec_review 可写结果文件
    并返回成功，供 dispatch_review 全链消费。
    """

    def __init__(self, project_root, result=None, gate_err=None, success=True):
        self.project_root = Path(project_root)
        self.result = result
        self.gate_err = gate_err
        self.success = success

    def _check_agent_result_artifact(self, spec_name, agent_type,
                                     run_started_at=None, wt_path=None):
        return self.gate_err

    def run_spec_review(self, spec_name, run_id=None):
        if self.result is not None:
            path = spec_review_result_path(self.project_root, spec_name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.result, ensure_ascii=False), encoding="utf-8")
        return MagicMock(success=self.success, run_id=run_id,
                         error=None if self.success else "boom")


class TestReviewFreezeClassification(unittest.TestCase):
    """fix-blocked-freeze-classification 5.1：评审路径归入「冻结转人工」。

    断言否决（rejected）与尝试耗尽（incomplete）两条路径均写 frozen=True
    且发出人工升级告警（severity major，含 findings 摘要 / 失败原因），
    admin_monitor 的 blocked_stuck 对这些 SPEC 不再唤起（冻结豁免），
    并验证「解冻 → 恢复 reviewing → 自动重派评审」恢复闭环可达。
    """

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _mk_project(self, spec_name="spec"):
        """构造 reviewing spec（带锚点 reviewer_run 与 spec 目录），返回 state_machine。"""
        sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", MagicMock())
        sm.add_spec(spec_name, {
            "status": "reviewing",
            "reviewer_run": f"spec-review-{spec_name}-123",
        })
        d = self.tmpdir / "spec" / "changes" / spec_name
        d.mkdir(parents=True, exist_ok=True)
        (d / "tasks.md").write_text("# Tasks\n- [ ] 1.1 do it\n", encoding="utf-8")
        return sm

    def _manager(self, sm=None, result=None, gate_err=None):
        """构造真实 SpecReviewManager（alert 走真实 PMEngine 落 AdminStore）。"""
        sm = sm or self._mk_project()
        from core.pm_engine import PMEngine
        engine = PMEngine(sm, MagicMock(), {}, self.tmpdir, MagicMock())
        engine._on_spec_ready = MagicMock()
        runner = _FakeRunner(self.tmpdir, result=result, gate_err=gate_err)
        return SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock()), sm, engine

    def _write_result(self, spec_name: str, data: dict):
        path = spec_review_result_path(self.tmpdir, spec_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _alerts(self, signal_type: str, spec: str) -> list:
        return [a for a in AdminStore(self.tmpdir, MagicMock()).read_all()
                if a.get("signal_type") == signal_type and a.get("spec") == spec]

    # ── 否决路径 ────────────────────────────────────────────────

    def test_rejected_frozen_with_alert(self):
        """达上限的评审否决 → frozen=True + spec-review-rejected 人工升级告警。

        2026-09-15 评审误判事故：首次 rejected 走自动复评（→ reviewing），仅当
        连续达 MAX_REJECT_REDO 次才冻结转人工。故此处预置计数到上一次，使本次
        否决为「达上限」的那一次。
        """
        mgr, sm, _ = self._manager()
        sm.update_spec("spec", {"_review_rejections": MAX_REJECT_REDO - 1})
        self._write_result("spec", {"status": "rejected",
                                    "findings": [{"severity": "blocking",
                                                  "aspect": "hole",
                                                  "detail": "缺关键路径",
                                                  "evidence": "proposal.md"}]})
        self.assertTrue(mgr.consume_review_result("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIs(entry.get(FROZEN_FIELD), True,
                      "达上限的评审否决必须写 frozen=True（否则 admin_monitor 不豁免）")
        err = str(entry.get("error") or "")
        self.assertIn("原状态 reviewing", err,
                      "冻结 error 必须内嵌「原状态 reviewing」（解冻恢复目标）")
        self.assertIn("spec-review-rejected: 缺关键路径", err)
        # 收口清理（同一原子写内清除，不携带 error 键覆盖冻结 error）
        self.assertIsNone(entry.get("reviewer_run"))
        self.assertEqual(str(entry.get("_review_attempts", "")), "0")
        alerts = self._alerts("spec-review-rejected", "spec")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], ESCALATION)
        self.assertEqual(alerts[0]["severity"], "major")
        self.assertIn("缺关键路径", alerts[0]["description"])
        self.assertIn("run_id=spec-review-spec-", alerts[0]["evidence"],
                      "告警 evidence 必须含本轮评审 run id")

    def test_first_rejection_redoes_not_freeze(self):
        """首次否决 → 不冻结不告警，回 reviewing 入队复评（不冻结合复评直调）。

        fix-spec-review-blocking-dispatch 改造：rejected 未达上限时不再递归
        直调 dispatch_review（同步阻塞），改为 pm_engine._enqueue 入队
        spec-review 由队列在 worker 线程异步派发。断言同步调整：检查入队记录
        而非 dispatch_review 被调用。
        """
        from unittest.mock import patch
        mgr, sm, engine = self._manager()
        with patch.object(engine, "_enqueue") as m_enqueue:
            self._write_result("spec", {"status": "rejected",
                                        "findings": [{"severity": "blocking",
                                                      "detail": "阈值不可达"}]})
            self.assertTrue(mgr.consume_review_result("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "reviewing",
                         "首次否决不得冻结，须回 reviewing 复评")
        self.assertIsNot(entry.get(FROZEN_FIELD), True)
        self.assertEqual(int(entry.get("_review_rejections", 0)), 1)
        self.assertEqual(self._alerts("spec-review-rejected", "spec"), [],
                         "自动复评阶段不得发人工升级告警")
        m_enqueue.assert_called_once_with("spec", "spec-review")

    def test_rejected_blocked_stuck_exempt(self):
        """冻结豁免：达上限冻结的评审否决 spec 不再触发 admin_monitor 的 blocked_stuck。"""
        mgr, sm, _ = self._manager()
        sm.update_spec("spec", {"_review_rejections": MAX_REJECT_REDO - 1})
        self._write_result("spec", {"status": "rejected", "findings": []})
        mgr.consume_review_result("spec")
        entry = dict(sm.read_one("spec"))
        # 回拨 updated 至阈值外，模拟「长期无人处置」（若豁免失效此时必唤起）
        entry["updated"] = (
            datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        mon = AdminMonitor.__new__(AdminMonitor)
        mon.admin_cfg = {"escalation_cooldown_minutes": 15}
        mon.logger = MagicMock()
        signals = mon._detect_blocked_stuck({"spec": entry}, time.time())
        self.assertEqual(
            [s for s in signals if s["spec"] == "spec"], [],
            "评审否决冻结的 spec 不得触发 blocked_stuck（admin 对方案无杠杆）",
        )

    def test_rejected_unfreeze_restores_reviewing_loop(self):
        """恢复闭环：parse_orig_status 解析「原状态 reviewing」→ 解冻恢复
        reviewing → _on_spec_reviewing 可重新派发评审（评审收口字段已清空）。"""
        mgr, sm, engine = self._manager()
        sm.update_spec("spec", {"_review_rejections": MAX_REJECT_REDO - 1})
        self._write_result("spec", {"status": "rejected",
                                    "findings": [{"severity": "blocking",
                                                  "detail": "方向性错误"}]})
        mgr.consume_review_result("spec")
        entry = sm.read_one("spec")
        # dashboard 解冻语义：parse_orig_status → unfreeze_spec(status=orig)
        orig = parse_orig_status(entry.get("error"))
        self.assertEqual(orig, "reviewing",
                         "评审冻结 error 必须能被 parse_orig_status 解析为 reviewing")
        self.assertTrue(sm.unfreeze_spec("spec", status=orig))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "reviewing")
        self.assertIsNot(entry.get(FROZEN_FIELD), True)
        self.assertIsNone(entry.get("reviewer_run"))
        self.assertEqual(str(entry.get("_review_attempts", "")), "0")
        # 自动重派评审：写入 approved 结果，dispatch_review 全链收口到 ready
        self._write_result("spec", {"status": "approved", "repairs": []})
        self.assertTrue(mgr.dispatch_review("spec"))
        self.assertEqual(sm.read_one("spec")["status"], "ready")

    # ── 尝试耗尽路径（两处：入口前置判定 + 失败计数达上限）─────────

    def test_exhausted_entry_gate_frozen_with_alert(self):
        """入口前置判定耗尽 → 冻结转人工 + spec-review-incomplete 告警。"""
        sm = self._mk_project()
        sm.update_spec("spec", {"reviewer_run": None,  # 清锚点，模拟上一轮失败已清
                                "_review_attempts": MAX_REVIEW_ATTEMPTS})
        mgr, sm, _ = self._manager(sm=sm)
        self.assertFalse(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIs(entry.get(FROZEN_FIELD), True)
        err = str(entry.get("error") or "")
        self.assertIn("原状态 reviewing", err)
        self.assertIn("spec-review-incomplete: 评审尝试已达上限", err)
        alerts = self._alerts("spec-review-incomplete", "spec")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "major")
        self.assertIn("连续失败", alerts[0]["description"])
        # 收口清理同 2.1
        self.assertIsNone(entry.get("reviewer_run"))
        self.assertEqual(str(entry.get("_review_attempts", "")), "0")

    def test_exhausted_failure_handler_frozen_with_alert(self):
        """失败计数达上限（_handle_review_failure 耗尽分支）→ 冻结转人工 + 告警。"""
        sm = self._mk_project()
        sm.update_spec("spec", {"_review_attempts": MAX_REVIEW_ATTEMPTS})
        mgr, sm, _ = self._manager(sm=sm)
        mgr._handle_review_failure("spec", "结果文件读取失败: x")
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIs(entry.get(FROZEN_FIELD), True)
        err = str(entry.get("error") or "")
        self.assertIn("原状态 reviewing", err)
        self.assertIn("spec-review-incomplete: 结果文件读取失败: x", err)
        alerts = self._alerts("spec-review-incomplete", "spec")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "major")
        self.assertIn("连续失败", alerts[0]["description"])
        self.assertIsNone(entry.get("reviewer_run"))
        self.assertEqual(str(entry.get("_review_attempts", "")), "0")

    def test_incomplete_unfreeze_restores_reviewing_loop(self):
        """尝试耗尽冻结的解冻闭环同否决路径：恢复 reviewing 可重派。"""
        sm = self._mk_project()
        sm.update_spec("spec", {"reviewer_run": None,
                                "_review_attempts": MAX_REVIEW_ATTEMPTS})
        mgr, sm, _ = self._manager(sm=sm)
        mgr.dispatch_review("spec")
        entry = sm.read_one("spec")
        orig = parse_orig_status(entry.get("error"))
        self.assertEqual(orig, "reviewing")
        self.assertTrue(sm.unfreeze_spec("spec", status=orig))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "reviewing")
        self.assertIsNot(entry.get(FROZEN_FIELD), True)

    def test_re_review_still_rejected_when_frozen(self):
        """re_review（重新评审入口）对冻结 spec 保持拒绝——评审类冻结的恢复
        走解冻而非 re_review（既有冻结保护契约，test_dashboard_api 同型）。

        fix-spec-review-blocking-dispatch 改造：rejected 未达上限不再递归
        dispatch_review 同步触发冻结（改为入队异步派发），故需预置冻结
        让测试语义不变——先让 spec 达冻结终态再验证 re_review 拒绝。
        """
        mgr, sm, _ = self._manager()
        # 预置冻结：rejections 已达上限-1，本次 rejected 消费达上限触发冻结
        sm.update_spec("spec", {"_review_rejections": MAX_REJECT_REDO - 1})
        self._write_result("spec", {"status": "rejected", "findings": []})
        mgr.consume_review_result("spec")
        entry = sm.read_one("spec")
        # 确认冻结已触发（消费达上限 → freeze_for_human）
        self.assertTrue(entry.get(FROZEN_FIELD), "预置冻结应触发 frozen=True")
        ok, msg = mgr.re_review("spec")
        self.assertFalse(ok)
        self.assertIn("冻结", msg)
        self.assertEqual(sm.read_one("spec")["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
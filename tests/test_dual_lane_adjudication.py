"""tests/test_dual_lane_adjudication.py — 双车道裁决流水线统一测试。

覆盖 add-declaration-relocation-protocol Task 5.3：
- full 与 fast-track 缺件走同源流水线（陈日走重定位 / 可软化走软化 /
  判据不明转终审 / 确认缺失走重派）
- 重定位不消耗重派预算
- fast-track 缺件 MUST NOT 直落重派
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.admin_store import DisputeAuditStore
from core.deliverables import snapshot_declaration_baseline
from core.pm_engine.engine import PMEngine
from core.state_machine import StateMachine
from core.agent_runner import AgentRunResult


class _FakeLogger:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass
    def debug(self, *a, **k): pass


def _write_spec(root: Path, tasks_text: str) -> Path:
    sd = root / "spec" / "changes" / "s1"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "tasks.md").write_text(tasks_text, encoding="utf-8")
    return sd


_DECL = ("# Tasks\n## Deliverables\n```yaml\n"
         "- path: core/a.py\n  kind: modify\n```\n"
         "## 1. T\n- [ ] 1.1 do\n")


class TestDualLaneSharedPipeline(unittest.TestCase):
    """full 和 fast-track 缺件走同源 _adjudicate_deliverable_missing"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / ".fenix").mkdir(exist_ok=True)
        self.sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", _FakeLogger())
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.runner = mock.MagicMock()
        self.wm = self.runner.worktree_manager
        self.wm.file_exists_on_branch.return_value = False
        self.engine = PMEngine(self.sm, self.runner, {}, self.tmpdir, _FakeLogger())
        self.wm.find_worktree_path.return_value = None

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_result(self, branch="fenix/s1"):
        return AgentRunResult("r1", "s1", "fast-track",
                              success=True, branch=branch, duration_seconds=1.0)

    def test_fast_track_missing_goes_to_judge_not_direct_redispatch(self):
        """fast-track 缺件 → 进入终审流水线（置 blocked），MUST NOT 直按缺件重派"""
        _write_spec(self.tmpdir, _DECL)
        self.sm.transition("s1", "implementing")
        self.wm.file_exists_on_branch.return_value = False
        self.runner.run_dispute_judge.return_value = AgentRunResult(
            "dispute-judge-s1-1", "s1", "dispute-judge",
            success=False, duration_seconds=1.0, error="boom")
        result = self._make_result()
        outcome = self.engine._adjudicate_deliverable_missing(
            "s1", result, None, ["core/a.py"], agent_type="fast-track")
        entry = self.sm.read_one("s1")
        self.assertEqual(outcome["action"], "handled")
        self.assertEqual(entry["status"], "blocked",
                         "fast-track 终审进行期置 blocked，不直接重派")
        self.assertTrue(
            "LLM 终审" in entry["error"],
            "error 注明终审进行中（与 full 车道一致）",
        )

    def test_full_lane_missing_goes_to_judge(self):
        """full 车道缺件 → 同一终审路径，行为一致"""
        _write_spec(self.tmpdir, _DECL)
        self.sm.transition("s1", "implementing")
        self.wm.file_exists_on_branch.return_value = False
        self.runner.run_dispute_judge.return_value = AgentRunResult(
            "dispute-judge-s1-1", "s1", "dispute-judge",
            success=False, duration_seconds=1.0, error="boom")
        result = AgentRunResult("r1", "s1", "implementer",
                                success=True, branch="fenix/s1",
                                duration_seconds=1.0)
        outcome = self.engine._adjudicate_deliverable_missing(
            "s1", result, None, ["core/a.py"], agent_type="implementer")
        entry = self.sm.read_one("s1")
        self.assertEqual(outcome["action"], "handled")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("LLM 终审", entry["error"])


    def test_prejudge_block_write_failure_does_not_abort(self):
        """终审前置 blocked 写盘失败（瞬态 STATE IO）→ WARNING 降级，不穿透
        裁决主体，judge run 照常派发兜底（code-review item c942deb9c1ff）"""
        _write_spec(self.tmpdir, _DECL)
        self.sm.transition("s1", "implementing")
        self.wm.file_exists_on_branch.return_value = False
        self.runner.run_dispute_judge.return_value = AgentRunResult(
            "dispute-judge-s1-1", "s1", "dispute-judge",
            success=False, duration_seconds=1.0, error="boom")
        real_update = self.sm.update_spec
        raised = []

        def flaky_update(name, updates, *a, **kw):
            if "LLM 终审进行中" in str((updates or {}).get("error", "")):
                raised.append(1)
                raise OSError("transient STATE.md io")
            return real_update(name, updates, *a, **kw)

        with mock.patch.object(self.sm, "update_spec",
                               side_effect=flaky_update):
            result = self._make_result()
            outcome = self.engine._adjudicate_deliverable_missing(
                "s1", result, None, ["core/a.py"], agent_type="fast-track")
        self.assertEqual(raised, [1], "终审置 blocked 写盘恰好失败一次且被吞")
        self.assertEqual(outcome["action"], "handled",
                         "STATE 写失败不穿透裁决主体，按 judge 结果正常收敛")
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "blocked",
                         "judge 失败 → unclear 归宿照常落终态 blocked")


class TestRelocationBudgetPreserved(unittest.TestCase):
    """重定位/软化不消耗重派预算（4.3 预算对齐）：relocate 全清 → proceed
    且 _retry_count 不递增"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / ".fenix").mkdir(exist_ok=True)
        self.sm = StateMachine(self.tmpdir / ".fenix" / "STATE.md", _FakeLogger())
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.runner = mock.MagicMock()
        self.wm = self.runner.worktree_manager
        self.wm.file_exists_on_branch.return_value = False
        self.wm.find_worktree_path.return_value = None
        self.engine = PMEngine(self.sm, self.runner, {}, self.tmpdir, _FakeLogger())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_relocation_does_not_increment_retry(self):
        """陈日重定位走重定位通道 → proceed，_retry_count 保持 0"""
        sd = _write_spec(self.tmpdir,
                         "## Deliverables\n```yaml\n"
                         "- path: core/old.py\n  kind: modify\n```\n"
                         "## 1. T\n- [ ] 1.1 do\n")
        (self.tmpdir / "core" / "other").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "core" / "other" / "old.py").write_text("x")
        self.wm.file_exists_on_branch.side_effect = lambda br, p: p == "core/other/old.py"
        result = AgentRunResult("r1", "s1", "implementer",
                                success=True, branch="fenix/s1",
                                duration_seconds=1.0)
        self.sm.transition("s1", "implementing")
        missing = [{"path": "core/old.py", "kind": "modify", "violation": "missing"}]
        outcome = self.engine._adjudicate_deliverable_missing(
            "s1", result, {"status": "success", "findings": []}, missing,
            agent_type="implementer")
        self.assertEqual(outcome["action"], "proceed",
                         "陈日重定位成功 → proceed（不走重派）")
        entry = self.sm.read_one("s1")
        self.assertEqual(entry.get("_retry_count", 0), 0,
                         "重定位不消耗重派预算")


# ── fix-admin-choice-payload-and-scenario-pairing 4.1：裁决 note 双车道 ──────

_PAYLOAD = ('{"scenarios": [{"id": "s1", "name": "修订后场景", "steps": []}], '
            '"reason": "原场景定义不可行", "fixture_files": []}')

_BASIS = "缺口可接受的依据" * 100


class TestChoicePayloadDualLaneNote(unittest.TestCase):
    """人工（alert-resolve note 从请求体直传）与 Administrator 自动
    （choice_payload 载荷优先）双车道收敛同一执行器 execute_adjudication_choice：
    - 自动车道载荷原文整体直达执行器（不经 actions_taken 拼接/截断）；
    - 缺载荷的 requires_payload 选项 skipped 不调执行器；
    - 非载荷选项 note 仍为依据文本截断 200 字（行为不变）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.proot = self.tmpdir / "proj"
        (self.proot / ".fenix").mkdir(parents=True)
        # s1 冻结态（force_advance 合法前置），字段集对齐 test_adjudication_choices
        lines = ["# Fenix Project State", "", "## Specs", "", "### s1",
                 "- status: blocked",
                 "- priority: 2",
                 "- created: 2026-01-01T00:00:00+00:00",
                 "- updated: 2026-01-02T00:00:00+00:00",
                 "- error: impl_budget_exhausted: 预算耗尽",
                 "- depends_on: null", ""]
        (self.proot / ".fenix" / "STATE.md").write_text("\n".join(lines),
                                                        encoding="utf-8")
        from core.admin_monitor import AdminMonitor

        self.mon = AdminMonitor.__new__(AdminMonitor)
        self.mon.project_root = self.proot
        self.mon.logger = _FakeLogger()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _disp(self, **kw):
        from core.agent_runner.result_gate import AdminDisposition

        kw.setdefault("run_id", "admin-run-dl1")
        kw.setdefault("spec", "s1")
        kw.setdefault("success", True)
        kw.setdefault("result", "resolved")
        return AdminDisposition(**kw)

    def _capture_executor(self):
        captured = {}

        def fake_executor(proot, spec, cid, note="", signal_type=""):
            captured.update({"note": note, "spec": spec, "choice_id": cid})
            return {"ok": True, "choice_id": cid, "action": cid,
                    "steps": [], "error": None}

        return captured, mock.patch(
            "core.dashboard.data.admin_actions.execute_adjudication_choice",
            side_effect=fake_executor,
        )

    def test_manual_lane_note_roundtrip_via_executor(self):
        """人工车道：note 直传执行器原文可达留痕（载荷通道不触碰该语义）。"""
        from core.dashboard.data.admin_actions import execute_adjudication_choice
        from core.state_machine import StateMachine

        r = execute_adjudication_choice(
            self.proot, "s1", "force_advance", note=_PAYLOAD,
            signal_type="impl_budget_exhausted")
        self.assertTrue(r["ok"])
        self.assertTrue(any(_PAYLOAD in s for s in r["steps"]),
                        f"note 原文须入留痕: {r['steps']}")
        entry = StateMachine(self.proot / ".fenix" / "STATE.md",
                             _FakeLogger()).read_one("s1")
        self.assertEqual(entry["status"], "done")

    def test_admin_lane_payload_verbatim_to_executor(self):
        """自动车道：choice_payload 非空 → note 取原文整体直传执行器。"""
        captured, patcher = self._capture_executor()
        with patcher:
            outcome = self.mon._apply_choice_execution(
                {"signal_type": "inconclusive_loop", "spec": "s1"},
                self._disp(choice_id="revise_scenario_reverify",
                           choice_payload=_PAYLOAD, actions_taken=_BASIS),
            )
        self.assertTrue(outcome["ok"])
        self.assertEqual(captured["note"], _PAYLOAD,
                         "载荷原文 MUST 整体直传（不经依据文本拼接/截断）")

    def test_admin_lane_missing_payload_skips_executor(self):
        """自动车道缺载荷：skipped 不调执行器，信号保留待重审。"""
        calls = []

        def forbidden_executor(*a, **k):
            calls.append(1)
            return {"ok": True, "steps": [], "error": None}

        with mock.patch(
            "core.dashboard.data.admin_actions.execute_adjudication_choice",
            side_effect=forbidden_executor,
        ):
            outcome = self.mon._apply_choice_execution(
                {"signal_type": "inconclusive_loop", "spec": "s1"},
                self._disp(choice_id="revise_scenario_reverify"),
            )
        self.assertIsNotNone(outcome)
        self.assertFalse(outcome["ok"])
        self.assertTrue(outcome.get("skipped"))
        self.assertIn("choice_payload", outcome.get("error") or "")
        self.assertEqual(calls, [], "缺载荷 MUST NOT 调执行器")

    def test_admin_lane_non_payload_note_is_basis_text(self):
        """非载荷选项：note 维持 actions_taken 截断 200 字现状。"""
        captured, patcher = self._capture_executor()
        with patcher:
            outcome = self.mon._apply_choice_execution(
                {"signal_type": "impl_budget_exhausted", "spec": "s1"},
                self._disp(choice_id="force_advance", actions_taken=_BASIS),
            )
        self.assertTrue(outcome["ok"])
        self.assertEqual(captured["note"], _BASIS[:200])


if __name__ == "__main__":
    unittest.main(verbosity=2)

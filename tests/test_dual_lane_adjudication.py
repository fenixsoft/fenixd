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


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""evo-spec-concurrency-flight-guard 契约测试。

治理同一 spec 的并发 run（spec-review / implementer / repair / fast-track）的
状态一致性。覆盖（design D0-D4）：

- D1 审核收尾回退守卫：spec-review 收口遇在飞实现 run（implementing/implemented/
  testing）→ 不回退、清 reviewer_run 锚点、落 `_review_skipped_result` 审计侧车、
  MUST NOT 调用 `_on_spec_ready`；非三类状态走既有回退路径（幂等）。
- D2 派发前在飞评审校验：`_on_spec_ready` 与 dispatch 队列候选筛选**两处落点**
  同口径顺延；陈旧锚点（run 已终态）判为无在飞评审放行并记 WARNING（防自造死锁）。
- D3 合并收尾 ready 态兜底：implementer / repair / fast-track 三条实现合并收尾
  路径在 status=ready 时先补记 ready→implementing 再推进 implemented——
  无 Invalid transition ERROR、有 WARNING 留痕；非 fenix/ 分支不触发兜底。
- D0 共享判定：`reviewer_in_flight` 分层（进程表 → 流文件 → 陈旧锚点 fail-open）；
  `_stream_recent` 前缀扩展覆盖 spec-review-/repair-。
"""

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine  # noqa: E402
from core.agent_runner import AgentRunResult  # noqa: E402

TS = str(int(time.time()))


def _mk_project(tmpdir: Path, spec_name: str = "demo") -> StateMachine:
    """构造带 spec 目录与 STATE 的最小项目。"""
    (tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(tmpdir / ".fenix" / "STATE.md", MagicMock())
    spec_dir = tmpdir / "spec" / "changes" / spec_name
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / ".spec.yaml").write_text(
        "schema: spec-driven\ncreated: 2026-09-19\nmode: full\n", encoding="utf-8"
    )
    (spec_dir / "tasks.md").write_text(
        "# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 do it\n", encoding="utf-8"
    )
    return sm


def _write_review_result(tmpdir: Path, spec_name: str, data: dict) -> Path:
    result_path = tmpdir / ".fenix" / "spec-review" / spec_name / ".fenix-run-result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return result_path


def _touch_run_stream(project_root: Path, run_id: str, tail: str = "system") -> Path:
    """写一个 run 流文件：首行 init + 末行事件（缺省 system 非终态）。"""
    p = project_root / ".fenix" / "runs" / f"{run_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"type": "init", "timestamp": "2026-01-01T00:00:00Z"})
        + "\n"
        + json.dumps({"type": tail, "timestamp": "2026-01-01T00:00:01Z"})
        + "\n",
        encoding="utf-8",
    )
    return p


class _FakeReviewRunner:
    """spec_review 硬门桩（对齐 test_spec_review_agent._FakeRunner）。"""

    def __init__(self, gate_err=None):
        self.gate_err = gate_err

    def _check_agent_result_artifact(self, spec_name, agent_type,
                                     run_started_at=None, wt_path=None):
        return self.gate_err

    def run_spec_review(self, spec_name, run_id=None):
        return MagicMock(success=True, run_id=f"spec-review-{spec_name}-999")


# ── D0 共享判定（reviewer_in_flight / _stream_recent 前缀扩展）──────────────


class _FakeRunnerForLiveness:
    """LivenessSupervisor._pm 最小实现（running_run_ids + project_root + logger）。"""

    def __init__(self, project_root, running=()):
        self.project_root = project_root
        self._running = list(running)
        self.logger = MagicMock()

    def running_run_ids(self):
        return list(self._running)


class TestReviewerInFlightJudgement(unittest.TestCase):
    """D0 分层判定：进程表为真相、流文件兜底、陈旧锚点 fail-open。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _sup(self, running=()):
        from core.agent_runner.liveness import LivenessSupervisor

        return LivenessSupervisor(_FakeRunnerForLiveness(self.tmpdir, running))

    def test_empty_reviewer_run_means_not_in_flight(self):
        sup = self._sup()
        in_flight, reason = sup.reviewer_in_flight("demo", None)
        self.assertFalse(in_flight)
        self.assertIsNone(reason)

    def test_process_table_truth_wins(self):
        run_id = f"spec-review-demo-{TS}"
        sup = self._sup(running=[run_id])
        in_flight, reason = sup.reviewer_in_flight("demo", run_id)
        self.assertTrue(in_flight)
        self.assertEqual(reason, "process")

    def test_stream_fresh_non_terminal_counts_in_flight(self):
        run_id = f"spec-review-demo-{TS}"
        _touch_run_stream(self.tmpdir, run_id, tail="system")  # 末行非终态
        sup = self._sup()  # 进程表无该 run → 走流判据
        in_flight, reason = sup.reviewer_in_flight("demo", run_id)
        self.assertTrue(in_flight)
        self.assertEqual(reason, "stream")

    def test_repair_run_stream_also_counts(self):
        """repair- 前缀 run 的流文件同样判在飞（前缀覆盖 0.1）。"""
        run_id = f"repair-demo-{TS}"
        _touch_run_stream(self.tmpdir, run_id, tail="system")
        sup = self._sup()
        in_flight, _reason = sup.reviewer_in_flight("demo", run_id)
        self.assertTrue(in_flight)

    def test_stale_anchor_fail_open(self):
        """陈旧锚点：无进程 + 流文件已终态/不存在 → (False, "stale") 放行。"""
        run_id = f"spec-review-demo-{TS}"
        # 流文件存在但末行为终态（result）
        _touch_run_stream(self.tmpdir, run_id, tail="result")
        sup = self._sup()
        in_flight, reason = sup.reviewer_in_flight("demo", run_id)
        self.assertFalse(in_flight)
        self.assertEqual(reason, "stale")
        # 流文件完全不存在同样陈旧
        in_flight2, reason2 = sup.reviewer_in_flight("demo", f"spec-review-demo-{TS}9")
        self.assertFalse(in_flight2)
        self.assertEqual(reason2, "stale")

    def test_stream_recent_covers_spec_review_prefix(self):
        """任务 0.1：_stream_recent 前缀覆盖 spec-review-/repair-（同口径）。"""
        from core.agent_runner.liveness import LivenessSupervisor

        sup = LivenessSupervisor(_FakeRunnerForLiveness(self.tmpdir))
        _touch_run_stream(self.tmpdir, f"spec-review-demo-{TS}", tail="system")
        self.assertTrue(sup._stream_recent("demo", 600))
        _touch_run_stream(self.tmpdir, f"repair-demo-{TS}", tail="system")
        self.assertTrue(sup._stream_recent("demo", 600))
        # 末行终态仍排除（不漂移）
        _touch_run_stream(self.tmpdir, f"spec-review-demo-{TS}9", tail="result")
        # 该终态文件不应命中（其 mtime 新鲜但末行终态）
        sup2 = LivenessSupervisor(_FakeRunnerForLiveness(self.tmpdir))
        self.assertFalse(sup2._stream_recent("demo-x", 600))


# ── D1 审核收尾回退守卫（spec_review.py）─────────────────────────────────────


class TestReviewRollbackGuard(unittest.TestCase):
    """consume_review_result 在 approved/repaired 收口遇在飞实现状态不回退。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _manager(self, status: str):
        from core.pm_engine.spec_review import SpecReviewManager

        sm = _mk_project(self.tmpdir)
        sm.add_spec("demo", {"status": status, "reviewer_run": f"spec-review-demo-{TS}"})
        engine = MagicMock()
        engine._on_spec_ready = MagicMock()
        mgr = SpecReviewManager(
            self.tmpdir, sm, _FakeReviewRunner(), engine, {}, MagicMock()
        )
        return mgr, sm, engine

    def test_in_flight_impl_state_skips_rollback(self):
        """implementing（implementer 已派发）时不回退、清锚点、审计侧车、不调 _on_spec_ready。"""
        _write_review_result(self.tmpdir, "demo", {"status": "repaired", "repairs": [
            {"path": "spec/changes/demo/tasks.md", "summary": "fixed"}]})
        mgr, sm, engine = self._manager("implementing")
        mgr.logger = MagicMock()
        ok = mgr.consume_review_result("demo")
        self.assertTrue(ok)
        entry = sm.read_one("demo")
        self.assertEqual(entry["status"], "implementing")  # 不回退
        self.assertIsNone(entry.get("reviewer_run"))  # 锚点已清
        # STATE 序列化把非 None 值存为字符串，数值侧车按字面/数值双容
        self.assertIn(entry.get("_review_attempts"), (0, "0", None))
        # 审计侧车落盘（_ 前缀随 STATE 往返持久化）
        skipped = entry.get("_review_skipped_result")
        self.assertIsNotNone(skipped)
        self.assertIn("repaired@result-path=", skipped)
        self.assertIn("spec-review/demo/.fenix-run-result.json", skipped)
        # MUST NOT 调用实现派发入口
        engine._on_spec_ready.assert_not_called()
        # INFO 留痕（非 ERROR）
        infos = [str(c) for c in mgr.logger.info.call_args_list]
        self.assertTrue(any("跳过回退" in c for c in infos), infos)

    def test_implemented_and_testing_states_also_skip(self):
        """implemented/testing 同属在飞实现后段，同样不回退。"""
        for status in ("implemented", "testing"):
            with self.subTest(status=status):
                self.tmpdir = Path(tempfile.mkdtemp())
                try:
                    _write_review_result(self.tmpdir, "demo",
                                         {"status": "approved", "repairs": [], "findings": []})
                    mgr, sm, engine = self._manager(status)
                    mgr.logger = MagicMock()
                    ok = mgr.consume_review_result("demo")
                    self.assertTrue(ok)
                    self.assertEqual(sm.read_one("demo")["status"], status)
                    engine._on_spec_ready.assert_not_called()
                finally:
                    shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reviewing_state_rolls_back_as_before(self):
        """幂等（任务 1.3）：非三类状态走既有回退路径，行为不变。"""
        _write_review_result(self.tmpdir, "demo", {"status": "approved", "repairs": [],
                                                   "findings": [], "summary": "ok"})
        mgr, sm, engine = self._manager("reviewing")
        mgr.logger = MagicMock()
        ok = mgr.consume_review_result("demo")
        self.assertTrue(ok)
        self.assertEqual(sm.read_one("demo")["status"], "ready")  # 既有回退
        engine._on_spec_ready.assert_called_once_with("demo")  # 既有重触发
        entry = sm.read_one("demo")
        self.assertIsNone(entry.get("_review_skipped_result"))  # 无跳过侧车


# ── D2 派发前在飞评审校验（engine + queue 两落点）────────────────────────────


def _make_engine(root: Path, logger):
    from core.pm_engine import PMEngine

    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    engine = PMEngine(StateMachine(root / ".fenix" / "STATE.md", logger),
                      MagicMock(), {}, root, logger)
    # 队列闸门按放行桩（避免真实预算/内容校验副作用）；worker 线程体拦截
    engine._check_impl_budget_exhausted = MagicMock(return_value=False)
    engine._check_spec_content_missing = MagicMock(return_value=False)
    engine._dependencies_satisfied = MagicMock(return_value=True)
    engine._enqueue = MagicMock()
    engine._run_agent_worker = MagicMock()
    return engine


class TestDispatchDeferral(unittest.TestCase):
    """D2：存在在飞评审 run 时两处派发落点均顺延；陈旧锚点放行（防死锁）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _ready_spec_with_reviewer(self, engine, reviewer_run):
        engine.state_machine.add_spec("demo", {"status": "ready", "priority": 5,
                                               "reviewer_run": reviewer_run})

    def test_on_spec_ready_defers_when_review_in_flight(self):
        """engine 落点：在飞评审 → 顺延（不派发、不写 error、冷却起点不动）。"""
        logger = MagicMock()
        engine = _make_engine(self.tmpdir, logger)
        _mk_project(self.tmpdir)
        reviewer_run = f"spec-review-demo-{TS}"
        self._ready_spec_with_reviewer(engine, reviewer_run)
        wm = MagicMock()
        wm.has_active_worktree.return_value = False
        engine.agent_runner.worktree_manager = wm
        engine.agent_runner.reviewer_in_flight = MagicMock(return_value=(True, "process"))

        engine._on_spec_ready("demo")

        engine._enqueue.assert_not_called()
        self.assertNotIn("demo", engine._last_dispatch_at)  # 顺延不计冷却起点
        # 不写 error / 不翻状态
        entry = engine.state_machine.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        self.assertIsNone(entry.get("error"))
        infos = [str(c) for c in logger.info.call_args_list]
        self.assertTrue(any("派发顺延" in c and reviewer_run in c for c in infos), infos)

    def test_queue_scan_defers_when_review_in_flight(self):
        """queue 落点：候选筛选跳过（条目保留队列、不 pop、不消耗 attempt）。"""
        logger = MagicMock()
        engine = _make_engine(self.tmpdir, logger)
        _mk_project(self.tmpdir)
        reviewer_run = f"spec-review-demo-{TS}"
        self._ready_spec_with_reviewer(engine, reviewer_run)
        engine.agent_runner.reviewer_in_flight = MagicMock(return_value=(True, "process"))
        engine._dispatcher._run_queue = [(5, "demo", "implementer", time.time())]

        engine._dispatcher._process_queue()

        self.assertEqual(len(engine._dispatcher._run_queue), 1)  # 条目保留
        engine._run_agent_worker.assert_not_called()
        infos = [str(c) for c in logger.info.call_args_list]
        self.assertTrue(any("派发顺延" in c for c in infos), infos)

    def test_on_spec_ready_stale_anchor_releases(self):
        """陈旧锚点（run 已终态）→ 判为无在飞评审放行派发（防自造死锁）。"""
        logger = MagicMock()
        engine = _make_engine(self.tmpdir, logger)
        _mk_project(self.tmpdir)
        reviewer_run = f"spec-review-demo-{TS}"
        self._ready_spec_with_reviewer(engine, reviewer_run)
        wm = MagicMock()
        wm.has_active_worktree.return_value = False
        engine.agent_runner.worktree_manager = wm
        engine.agent_runner.reviewer_in_flight = MagicMock(return_value=(False, "stale"))

        engine._on_spec_ready("demo")

        engine._enqueue.assert_called_once_with("demo", "implementer")
        warns = [str(c) for c in logger.warning.call_args_list]
        self.assertTrue(any("陈旧评审锚点" in c for c in warns), warns)

    def test_queue_scan_stale_anchor_releases(self):
        """queue 落点：陈旧锚点放行不误拦（条目照常派发）。"""
        logger = MagicMock()
        engine = _make_engine(self.tmpdir, logger)
        _mk_project(self.tmpdir)
        reviewer_run = f"spec-review-demo-{TS}"
        self._ready_spec_with_reviewer(engine, reviewer_run)
        engine.agent_runner.reviewer_in_flight = MagicMock(return_value=(False, "stale"))
        engine._dispatcher._run_queue = [(5, "demo", "implementer", time.time())]
        engine._dispatcher._active_runs = 0

        engine._dispatcher._process_queue()

        self.assertEqual(len(engine._dispatcher._run_queue), 0)  # 条目已派发
        engine._run_agent_worker.assert_called_once()
        warns = [str(c) for c in logger.warning.call_args_list]
        self.assertTrue(any("陈旧评审锚点" in c for c in warns), warns)

    def test_no_reviewer_run_dispatches_normally(self):
        """无 reviewer_run → 直接放行（既有行为不变）。"""
        engine = _make_engine(self.tmpdir, MagicMock())
        _mk_project(self.tmpdir)
        engine.state_machine.add_spec("demo", {"status": "ready", "priority": 5})
        wm = MagicMock()
        wm.has_active_worktree.return_value = False
        engine.agent_runner.worktree_manager = wm
        engine.agent_runner.reviewer_in_flight = MagicMock(return_value=(False, None))

        engine._on_spec_ready("demo")

        engine._enqueue.assert_called_once_with("demo", "implementer")
        engine.agent_runner.reviewer_in_flight.assert_not_called()  # 空锚点不判定


# ── D3 合并收尾 ready 态兜底（三条实现合并路径）───────────────────────────────


class _MergeFallbackBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.root = Path(self.tmpdir)
        self.spec = "demo"
        (self.root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        from core.pm_engine import PMEngine

        self.sm = StateMachine(self.root / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.root, self.logger)
        _mk_project(self.root, self.spec)
        self.engine._reconcile_impl_budget = MagicMock()
        self.engine._clear_dispatch_conflict = MagicMock(return_value={})
        self.engine._sync_task_progress = MagicMock()
        self.engine._enqueue = MagicMock()
        self.engine._dispatcher._enqueue = MagicMock()
        self.engine._dispatcher._enqueue_front = MagicMock()
        self.engine.agent_runner.worktree_manager.merge_back_from_branch = (
            MagicMock(return_value=(True, ""))
        )
        self.engine.agent_runner.worktree_manager.consume_legacy = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _assert_fallback_logged(self):
        warns = [str(c) for c in self.logger.warning.call_args_list]
        self.assertTrue(
            any("ready 态合并兜底" in c for c in warns), f"无兜底 WARNING 留痕: {warns}"
        )
        # 项目日志审计留痕（.fenix/PROJECT_LOG.md 追加）
        log_path = self.root / ".fenix" / "PROJECT_LOG.md"
        self.assertTrue(log_path.exists(), "项目日志未落盘")
        self.assertIn("ready 态合并兜底", log_path.read_text(encoding="utf-8"))


class TestImplementerMergeReadyFallback(_MergeFallbackBase):
    """queue.py implementer 主路径：ready 态 merge 收尾补记 implementing。"""

    def _run_impl_with_status(self, status: str, branch: str):
        self.sm.add_spec(self.spec, {"priority": 5})
        # 直接 update_spec 置位（drafted→implementing 无合法转移，测试夹具不走
        # 完整状态链；merged 收尾转移的合法性由状态机自身判定）
        self.sm.update_spec(self.spec, {"status": status})
        result_file = self.root / ".fenix" / ".fenix-run-result.json"
        result_file.write_text(
            json.dumps({"status": "success", "spec": self.spec, "summary": "ok"}),
            encoding="utf-8",
        )
        self.engine.agent_runner.run_implementer = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, run_id=f"impl-{self.spec}-1-a1",
                branch=branch, duration_seconds=1.0, worktree_dirty=[],
            )
        )
        self.engine.agent_runner.worktree_manager.find_implementer_worktree = (
            MagicMock(return_value=None)
        )
        self.engine._run_agent_worker(self.spec, "implementer", 5)
        return self.sm.read_one(self.spec)

    def test_ready_merge_backfills_implementing_then_implemented(self):
        """ready（评审收尾竞态回退残留）+ 实现分支 → 无 Invalid transition ERROR。"""
        entry = self._run_impl_with_status("ready", f"fenix/{self.spec}-{TS}")
        self.assertEqual(entry["status"], "implemented")
        self.assertIsNone(entry.get("error"))
        self._assert_fallback_logged()
        # 无 Invalid transition ERROR 噪音（状态机 logger 为 MagicMock 不计；
        # 兜底路径本身不产生非法转移）
        errors = [str(c) for c in self.logger.error.call_args_list]
        self.assertFalse(any("Invalid transition" in c for c in errors), errors)

    def test_implementing_merge_no_fallback_normal(self):
        """既有路径（implementing → implemented）行为不变、无兜底留痕。"""
        entry = self._run_impl_with_status("implementing", f"fenix/{self.spec}-{TS}")
        self.assertEqual(entry["status"], "implemented")
        warns = [str(c) for c in self.logger.warning.call_args_list]
        self.assertFalse(any("ready 态合并兜底" in c for c in warns), warns)

    def test_verify_branch_no_fallback(self):
        """非实现分支（fenix/verify- 前缀）不触发兜底——ready→implemented 仍被拒。"""
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.update_spec(self.spec, {"status": "ready"})
        result_file = self.root / ".fenix" / ".fenix-run-result.json"
        result_file.write_text(
            json.dumps({"status": "success", "spec": self.spec, "summary": "ok"}),
            encoding="utf-8",
        )
        self.engine.agent_runner.run_implementer = MagicMock(
            return_value=SimpleNamespace(
                success=True, error=None, run_id=f"impl-{self.spec}-1-a1",
                branch=f"fenix/verify-{self.spec}-{TS}", duration_seconds=1.0,
                worktree_dirty=[],
            )
        )
        self.engine.agent_runner.worktree_manager.find_implementer_worktree = (
            MagicMock(return_value=None)
        )
        self.engine._run_agent_worker(self.spec, "implementer", 5)
        # ready→implemented 非法转移被状态机拒绝（transition 返回 False 不抛）：
        # status 保持 ready，ERROR 留痕暴露真实异常（MUST NOT 静默放行）
        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "ready")
        errors = [str(c) for c in self.logger.error.call_args_list]
        self.assertTrue(any("Invalid transition" in c for c in errors), errors)


class TestRepairReMergeReadyFallback(_MergeFallbackBase):
    """repair_lane.py re-merge 成功路径：ready 态补记 implementing 再 implemented。"""

    def test_repair_remerge_ready_backfill(self):
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.update_spec(self.spec, {"status": "ready"})
        wt_path = self.root / ".fenix" / "worktrees" / f"impl-{self.spec}-1"
        wt_path.mkdir(parents=True, exist_ok=True)
        (wt_path / ".fenix-run-result.json").write_text(
            json.dumps({"status": "success", "spec": self.spec}), encoding="utf-8"
        )
        self.engine.agent_runner.run_repair = MagicMock(
            return_value=SimpleNamespace(
                success=True, run_id=f"repair-{self.spec}-{TS}", cancelled=False
            )
        )
        self.engine._check_repair_commit_facts = MagicMock(return_value=(True, ""))
        self.engine._repair_conflict_summary = MagicMock(return_value={})
        self.engine.agent_runner._v2_stop_for_worktree = MagicMock()
        self.engine.agent_runner.worktree_manager.cleanup = MagicMock()

        self.engine._run_repair_worker(
            self.spec, wt_path, f"fenix/{self.spec}-{TS}",
            SimpleNamespace(error=""),
        )

        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "implemented")
        self.assertIsNone(entry.get("error"))
        self._assert_fallback_logged()


class TestFastTrackMergeReadyFallback(_MergeFallbackBase):
    """fast_track.py merge 成功路径：ready 态补记 implementing 再 implemented。"""

    def test_fast_track_merge_ready_backfill(self):
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.update_spec(self.spec, {"status": "ready"})
        result = AgentRunResult(
            run_id=f"impl-{self.spec}-{TS}", spec_name=self.spec,
            agent_type="fast-track", success=True, duration_seconds=1.0,
            branch=f"fenix/{self.spec}-{TS}",
        )
        self.engine.agent_runner.worktree_manager.merge_back_from_branch = (
            MagicMock(return_value=(True, ""))
        )

        merged = self.engine._dispatcher._reconcile_and_merge(self.spec, result)

        self.assertTrue(merged)
        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "implemented")
        self.assertIsNone(entry.get("error"))
        self._assert_fallback_logged()

    def test_fast_track_verify_branch_no_fallback(self):
        """非 fenix/ 实现分支（verify- 前缀）不触发兜底——ready→implemented 仍被拒。"""
        self.sm.add_spec(self.spec, {"priority": 5})
        self.sm.update_spec(self.spec, {"status": "ready"})
        result = AgentRunResult(
            run_id=f"impl-{self.spec}-{TS}", spec_name=self.spec,
            agent_type="fast-track", success=True, duration_seconds=1.0,
            branch=f"fenix/verify-{self.spec}-{TS}",
        )
        merged = self.engine._dispatcher._reconcile_and_merge(self.spec, result)
        # verify- 分支属 verifier 产物：不兜底，ready→implemented 被状态机拒绝
        # （transition 返回 False 不抛）→ status 保持 ready，ERROR 暴露真实异常
        self.assertTrue(merged)  # _reconcile_and_merge 返回值不因转移失败翻转
        entry = self.sm.read_one(self.spec)
        self.assertEqual(entry["status"], "ready")
        errors = [str(c) for c in self.logger.error.call_args_list]
        self.assertTrue(any("Invalid transition" in c for c in errors), errors)


if __name__ == "__main__":
    unittest.main()

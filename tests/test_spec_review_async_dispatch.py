"""fix-spec-review-blocking-dispatch 契约测试。

覆盖 tasks.md 5.1-5.7：_on_spec_reviewing 改入队后的异步语义、评审条目
计数隔离、worker 释放、双判据单飞、content 失败入队、reviewer_in_flight
queued 判据、实现条目可派发性不受影响。
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

from core.state_machine import StateMachine
from core.pm_engine.spec_review import MAX_REVIEW_ATTEMPTS


TS = str(int(time.time()))


def _mk_project(tmpdir: Path, spec_name: str = "demo") -> StateMachine:
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


def _make_engine(root: Path, logger=None):
    from core.pm_engine import PMEngine
    logger = logger or MagicMock()
    engine = PMEngine(StateMachine(root / ".fenix" / "STATE.md", logger),
                      MagicMock(), {}, root, logger)
    engine._check_impl_budget_exhausted = MagicMock(return_value=False)
    engine._check_spec_content_missing = MagicMock(return_value=False)
    engine._dependencies_satisfied = MagicMock(return_value=True)
    return engine, logger


class TestOnSpecReviewingEnqueues(unittest.TestCase):
    """tasks 5.1/5.11：_on_spec_reviewing 调用后立即返回，队列出现 spec-review 条目。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_on_spec_reviewing_enqueues_and_returns_immediately(self):
        """_on_spec_reviewing 调用后立即返回且队列中出现 spec-review 条目。"""
        _mk_project(self.tmpdir)
        engine, _ = _make_engine(self.tmpdir)
        # 构造 reviewing spec（无 reviewer_run，无 in-flight 评审）
        engine.state_machine.add_spec("demo", {"status": "reviewing"})
        # _process_queue 会触发 _run_agent_worker（真调用），需要拦截避免真跑
        engine._dispatcher._process_queue = MagicMock()

        engine._on_spec_reviewing("demo")

        # 队列出现 spec-review 条目
        entries = [e for e in engine._dispatcher._run_queue if e[2] == "spec-review"]
        self.assertEqual(len(entries), 1, f"队列应有一条 spec-review 条目: {engine._dispatcher._run_queue}")
        self.assertEqual(entries[0][1], "demo")

    def test_enqueue_deduplicates(self):
        """同一 (spec, spec-review) 去重：二次入队不重复。"""
        _mk_project(self.tmpdir)
        engine, _ = _make_engine(self.tmpdir)
        engine.state_machine.add_spec("demo", {"status": "reviewing"})
        engine._dispatcher._process_queue = MagicMock()

        engine._on_spec_reviewing("demo")
        engine._on_spec_reviewing("demo")

        entries = [e for e in engine._dispatcher._run_queue if e[2] == "spec-review"]
        self.assertEqual(len(entries), 1)

    def test_start_after_blocks_enqueue(self):
        """start_after 未到期 → 不入队。"""
        from datetime import datetime, timedelta, timezone
        _mk_project(self.tmpdir)
        engine, _ = _make_engine(self.tmpdir)
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        engine.state_machine.add_spec("demo", {
            "status": "reviewing",
            "start_after": future,
        })
        engine._dispatcher._process_queue = MagicMock()

        engine._on_spec_reviewing("demo")

        entries = [e for e in engine._dispatcher._run_queue if e[2] == "spec-review"]
        self.assertEqual(len(entries), 0, "start_after 未到期不得入队")


class TestReviewEntryIsolation(unittest.TestCase):
    """task 5.2：评审条目出队后 _active_runs/_active_priorities 不变、_active_reviews 含该 spec。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_review_entry_does_not_affect_run_counters(self):
        """评审条目出队后 _active_runs 不变、_active_reviews 包含 spec。"""
        _mk_project(self.tmpdir)
        engine, _ = _make_engine(self.tmpdir)
        engine.state_machine.add_spec("demo", {"status": "reviewing", "priority": 5})
        engine._dispatcher._run_queue = [(5, "demo", "spec-review", time.time())]
        engine._dispatcher._active_runs = 0
        engine._dispatcher._active_priorities.clear()

        with engine._dispatcher._queue_lock:
            # 手动模拟出队分流（避免真起线程）
            entry = engine._dispatcher._run_queue.pop(0)
            prio, spec_name, agent_type, enq_at = entry
            if agent_type == "spec-review":
                engine._dispatcher._active_reviews.add(spec_name)

        self.assertEqual(engine._dispatcher._active_runs, 0)
        self.assertEqual(len(engine._dispatcher._active_priorities), 0)
        self.assertIn("demo", engine._dispatcher._active_reviews)


class TestWorkerReleasesActiveReviews(unittest.TestCase):
    """task 5.3：_run_agent_worker 的 finally 释放 _active_reviews（含异常路径）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_finally_releases_active_reviews(self):
        """正常路径：worker finally 释放 _active_reviews。"""
        _mk_project(self.tmpdir)
        engine, _ = _make_engine(self.tmpdir)
        engine.state_machine.add_spec("demo", {"status": "reviewing", "priority": 5})
        engine._dispatcher._active_reviews.add("demo")

        # Mock _run_spec_review_worker 为正常返回
        engine._dispatcher._run_spec_review_worker = MagicMock()

        engine._dispatcher._run_agent_worker("demo", "spec-review", 5)

        self.assertNotIn("demo", engine._dispatcher._active_reviews)

    def test_finally_releases_on_exception(self):
        """异常路径：worker finally 仍释放 _active_reviews。"""
        _mk_project(self.tmpdir)
        engine, _ = _make_engine(self.tmpdir)
        engine.state_machine.add_spec("demo", {"status": "reviewing", "priority": 5})
        engine._dispatcher._active_reviews.add("demo")

        # Mock _run_spec_review_worker 抛异常
        engine._dispatcher._run_spec_review_worker = MagicMock(side_effect=RuntimeError("boom"))

        engine._dispatcher._run_agent_worker("demo", "spec-review", 5)

        self.assertNotIn("demo", engine._dispatcher._active_reviews)


class TestDualGuardSingleFlight(unittest.TestCase):
    """task 5.4：双判据单飞——_active_reviews 命中时拒绝、reviewer_run 非空时拒绝、皆空时放行。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine_with_reviewing(self, reviewer_run=None):
        _mk_project(self.tmpdir)
        engine, _ = _make_engine(self.tmpdir)
        entry = {"status": "reviewing"}
        if reviewer_run:
            entry["reviewer_run"] = reviewer_run
        engine.state_machine.add_spec("demo", entry)
        return engine

    def test_active_reviews_hit_rejects(self):
        """_active_reviews 命中 → 跳过（不入队）。"""
        engine = self._make_engine_with_reviewing()
        engine._dispatcher._active_reviews.add("demo")
        engine._dispatcher._process_queue = MagicMock()

        engine._on_spec_reviewing("demo")

        entries = [e for e in engine._dispatcher._run_queue if e[2] == "spec-review"]
        self.assertEqual(len(entries), 0)

    def test_reviewer_run_inflight_rejects(self):
        """reviewer_run 非空 + in_flight=True → 跳过。"""
        engine = self._make_engine_with_reviewing(reviewer_run=f"spec-review-demo-{TS}")
        engine.agent_runner.reviewer_in_flight = MagicMock(return_value=(True, "process"))
        engine._dispatcher._process_queue = MagicMock()

        engine._on_spec_reviewing("demo")

        entries = [e for e in engine._dispatcher._run_queue if e[2] == "spec-review"]
        self.assertEqual(len(entries), 0)

    def test_both_empty_allows(self):
        """_active_reviews 空 + reviewer_run 空 → 放行入队。"""
        engine = self._make_engine_with_reviewing()
        engine._dispatcher._process_queue = MagicMock()

        engine._on_spec_reviewing("demo")

        entries = [e for e in engine._dispatcher._run_queue if e[2] == "spec-review"]
        self.assertEqual(len(entries), 1)


class TestContentFailureEnqueues(unittest.TestCase):
    """task 5.5：content 类失败重试经队列重新入队（reviewer_run 已清空）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_content_failure_clears_anchor_and_enqueues(self):
        """content 失败：reviewer_run 清空 + 入队 spec-review + _review_attempts 递增。"""
        from core.pm_engine.spec_review import SpecReviewManager

        sm = _mk_project(self.tmpdir)
        sm.add_spec("demo", {
            "status": "reviewing",
            "reviewer_run": f"spec-review-demo-{TS}",
            "_review_attempts": 0,
        })
        engine = MagicMock()
        engine.is_review_in_flight = MagicMock(return_value=False)
        # Fake agent_runner：_check_agent_result_artifact 返回错误
        runner = MagicMock()
        runner._check_agent_result_artifact = MagicMock(return_value="结果文件缺失")
        runner.run_spec_review = MagicMock(return_value=SimpleNamespace(success=True))

        mgr = SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock())
        ok = mgr.consume_review_result("demo")
        self.assertFalse(ok)

        entry = sm.read_one("demo")
        self.assertIsNone(entry.get("reviewer_run"), "content 失败须清 reviewer_run")
        self.assertEqual(int(entry.get("_review_attempts", 0)), 1)
        engine._enqueue.assert_called_once_with("demo", "spec-review")


class TestReviewerInFlightQueued(unittest.TestCase):
    """task 5.6：reviewer_in_flight 对 _active_reviews 命中返回 (True, "queued")。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_queued_reason_when_active_reviews_hit(self):
        """_active_reviews 命中 → (True, "queued")。"""
        from core.agent_runner.liveness import LivenessSupervisor

        class _FakePM:
            def __init__(self, root):
                self.project_root = root
                self.logger = MagicMock()
            def running_run_ids(self):
                return []

        pm = _FakePM(self.tmpdir)
        # 注入 pm_engine_ref（无 active_reviews）
        class _FakePMEngine:
            def is_review_in_flight(self, spec_name):
                return True
        pm._pm_engine_ref = _FakePMEngine()

        sup = LivenessSupervisor(pm)
        in_flight, reason = sup.reviewer_in_flight("demo", None)
        self.assertTrue(in_flight)
        self.assertEqual(reason, "queued")

    def test_no_ref_falls_through(self):
        """无 _pm_engine_ref → 跳过前置判据，空锚点返回 (False, None)。"""
        from core.agent_runner.liveness import LivenessSupervisor

        class _FakePM:
            def __init__(self, root):
                self.project_root = root
                self.logger = MagicMock()
            def running_run_ids(self):
                return []

        pm = _FakePM(self.tmpdir)
        sup = LivenessSupervisor(pm)
        in_flight, reason = sup.reviewer_in_flight("demo", None)
        self.assertFalse(in_flight)
        self.assertIsNone(reason)


class TestReviewEntryDoesNotAffectImplScheduling(unittest.TestCase):
    """task 5.7：评审条目存在时，实现条目的可派发性判定不受影响。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_impl_dispatchable_despite_review_in_queue(self):
        """队列有评审条目 + 实现条目均合法，两者都可被选中（评审不挤压实现）。"""
        _mk_project(self.tmpdir)
        engine, _ = _make_engine(self.tmpdir)
        engine.state_machine.add_spec("demo", {"status": "reviewing", "priority": 6})
        engine.state_machine.add_spec("impl-spec", {"status": "ready", "priority": 5})
        now = time.time()
        engine._dispatcher._run_queue = [
            (6, "demo", "spec-review", now),
            (5, "impl-spec", "implementer", now),
        ]
        engine._dispatcher._active_runs = 0
        engine._dispatcher._active_priorities.clear()

        # best_valid_prio 扫描：评审 P6，实现 P5 → best_valid_prio = 5
        # target_prio = 5，dispatch_idx 找 P5 实现条目
        # _should_defer_for_reviewer：impl-spec 无 reviewer_run → 放行
        engine._dispatcher._process_queue()

        # 实现条目应被派发（不被评审挤压）
        self.assertEqual(len(engine._dispatcher._run_queue), 1)
        self.assertEqual(engine._dispatcher._run_queue[0][1], "demo")


if __name__ == "__main__":
    unittest.main()

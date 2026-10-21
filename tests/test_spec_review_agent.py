"""tests for spec-review-agent: result consumption, write-boundary, recovery.

Covers:
- Three-status mechanical consumption (approved/repaired → ready, rejected → blocked)
- Retry counting & exhausted → blocked with spec-review-incomplete: prefix
- Re-review entry conditions (4 rejection classes)
- Write-boundary validation classes
"""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, REVIEW_REJECTED_FREEZE_ERROR_PREFIX
from core.pm_engine.infra_breaker import InfraCircuitBreaker
from core.pm_engine.spec_review import SpecReviewManager, MAX_REVIEW_ATTEMPTS, MAX_REJECT_REDO


def _stub_pm():
    """MagicMock pm_engine + is_review_in_flight stub（fix-spec-review-blocking-dispatch）。

    dispatch_review 入口新增 `pm_engine.is_review_in_flight` 在飞判据；裸 MagicMock
    对其调用返回 MagicMock（真值）会把 dispatch_review 拒派。此处 stub 为 False
    （无在飞评审），使测试聚焦于既有评审语义。
    """
    m = MagicMock()
    m.is_review_in_flight = MagicMock(return_value=False)
    return m


def _mk_project(tmpdir: Path, spec_name="spec"):
    """Create a minimal project with a drafted spec and spec dir."""
    (tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(tmpdir / ".fenix" / "STATE.md", MagicMock())
    sm.add_spec(spec_name, {"status": "reviewing", "reviewer_run": f"spec-review-{spec_name}-123"})
    (tmpdir / "spec" / "changes" / spec_name).mkdir(parents=True, exist_ok=True)
    (tmpdir / "spec" / "changes" / spec_name / "tasks.md").write_text(
        "# Tasks\n- [ ] 1.1 do it\n", encoding="utf-8"
    )
    return sm


def _write_result(tmpdir: Path, spec_name: str, data: dict):
    """Write a review result file to the spec-review dir."""
    result_path = tmpdir / ".fenix" / "spec-review" / spec_name / ".fenix-run-result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return result_path


class _FakeRunner:
    """Minimal agent_runner stub exposing hard-gate API."""

    def __init__(self, gate_err=None):
        self.gate_err = gate_err

    def _check_agent_result_artifact(self, spec_name, agent_type,
                                     run_started_at=None, wt_path=None):
        return self.gate_err

    def run_spec_review(self, spec_name, run_id=None):
        return MagicMock(success=True, run_id=f"spec-review-{spec_name}-999")


class TestConsumeReviewResult(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _manager(self, sm=None, runner=None):
        sm = sm or _mk_project(self.tmpdir)
        runner = runner or _FakeRunner()
        engine = MagicMock()
        engine.is_review_in_flight = MagicMock(return_value=False)
        engine._on_spec_ready = MagicMock()
        return SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock()), sm, engine

    def _set_status(self, sm, status):
        sm.update_spec("spec", {"status": status})

    def test_approved_goes_ready(self):
        _write_result(self.tmpdir, "spec", {"status": "approved", "repairs": [],
                                            "findings": [], "summary": "ok"})
        mgr, sm, engine = self._manager()
        mgr.consume_review_result("spec")
        self.assertEqual(sm.read_one("spec")["status"], "ready")
        engine._on_spec_ready.assert_called_once_with("spec")

    def test_repaired_goes_ready(self):
        _write_result(self.tmpdir, "spec", {"status": "repaired", "repairs": [
            {"path": "spec/changes/spec/tasks.md", "summary": "fixed"}]})
        mgr, sm, engine = self._manager()
        ok = mgr.consume_review_result("spec")
        self.assertTrue(ok)
        self.assertEqual(sm.read_one("spec")["status"], "ready")

    def test_rejected_goes_blocked_with_prefix(self):
        # 2026-09-15 评审误判事故：首次 rejected 走「自动复评」（→ reviewing），
        # 仅当连续达 MAX_REJECT_REDO 次仍 rejected 才冻结转人工。故此处预置
        # 计数到上限前一步，使本次否决为「达上限」的那一次，可直接断言冻结语义。
        mgr, sm, engine = self._manager()
        sm.update_spec("spec", {"_review_rejections": MAX_REJECT_REDO - 1})
        _write_result(self.tmpdir, "spec", {"status": "rejected",
                                            "findings": [{"severity": "blocking",
                                                          "aspect": "hole",
                                                          "detail": "缺关键路径",
                                                          "evidence": "proposal.md"}]})
        mgr.consume_review_result("spec")
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "blocked")
        # fix-blocked-freeze-classification 2.1：否决路径改走「冻结转人工」——
        # frozen=True + 原状态 reviewing 内嵌（解冻恢复 reviewing 自动重派评审），
        # spec-review-rejected 前缀保留在 error 内供人工恢复入口识别
        self.assertIs(entry.get("frozen"), True)
        err = str(entry.get("error", ""))
        self.assertIn("spec-review-rejected:", err)
        self.assertIn("原状态 reviewing", err)

    def test_first_rejection_triggers_redo_not_freeze(self):
        """首次 rejected → 不冻结，回 reviewing 入队复评（防误判转人工）。

        fix-spec-review-blocking-dispatch 改造：rejected 未达上限时不再递归
        dispatch_review（同步阻塞），改为 pm_engine._enqueue 入队
        spec-review 由队列在 worker 线程异步派发。断言同步调整：检查入队记录
        而非 dispatch_review 被调用。
        """
        mgr, sm, engine = self._manager()
        _write_result(self.tmpdir, "spec", {"status": "rejected",
                                            "findings": [{"severity": "blocking",
                                                          "aspect": "hole",
                                                          "detail": "阈值不可达",
                                                          "evidence": "design.md"}]})
        ok = mgr.consume_review_result("spec")
        self.assertTrue(ok)
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "reviewing",
                         "首次否决不得冻结，须回 reviewing 复评")
        self.assertIsNot(entry.get("frozen"), True, "首次否决不得置 frozen")
        self.assertEqual(int(entry.get("_review_rejections", 0)), 1)
        self.assertIsNone(entry.get("reviewer_run"))
        err = str(entry.get("error") or "")
        self.assertIn("spec-review-rejected: 阈值不可达", err,
                      "否决摘要须留在 error 供复评注入")
        engine._enqueue.assert_called_once_with("spec", "spec-review")

    def test_rejection_counter_cleared_on_pass(self):
        """通过（approved/repaired）即清零否决计数，下次评审从零起算。"""
        mgr, sm, engine = self._manager()
        sm.update_spec("spec", {"_review_rejections": 1})
        _write_result(self.tmpdir, "spec", {"status": "approved", "repairs": [],
                                            "findings": [], "summary": "ok"})
        mgr.consume_review_result("spec")
        self.assertEqual(int(sm.read_one("spec").get("_review_rejections", 0)), 0)

    def test_gate_failure_retries_not_blocked(self):
        """Gate failure → attempt counted, spec stays reviewing, not blocked yet."""
        _mk_project(self.tmpdir)
        runner = _FakeRunner(gate_err="结果文件缺失")
        mgr, sm, engine = self._manager(runner=runner)
        mgr.consume_review_result("spec")
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "reviewing")
        self.assertEqual(int(entry.get("_review_attempts", 0)), 1)  # failure handler counts 1

    def test_exhausted_attempts_blocks_with_incomplete(self):
        """Attempts exhausted → blocked with spec-review-incomplete: prefix."""
        _mk_project(self.tmpdir)
        runner = _FakeRunner(gate_err="结果文件缺失")
        mgr, sm, engine = self._manager(runner=runner)
        # Simulate attempts already exhausted
        sm.update_spec("spec", {"_review_attempts": MAX_REVIEW_ATTEMPTS})
        mgr.consume_review_result("spec")
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "blocked")
        # fix-blocked-freeze-classification 2.2：耗尽路径改走冻结转人工
        self.assertIs(entry.get("frozen"), True)
        err = str(entry.get("error", ""))
        self.assertIn("spec-review-incomplete:", err)
        self.assertIn("原状态 reviewing", err)

    def test_recheck_clears_attempts_on_success(self):
        _mk_project(self.tmpdir)
        mgr, sm, engine = self._manager()
        sm.update_spec("spec", {"_review_attempts": 2})
        _write_result(self.tmpdir, "spec", {"status": "approved", "repairs": []})
        mgr.consume_review_result("spec")
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(int(entry.get("_review_attempts", -1)), 0)

    def test_boundary_failure_counts_as_content_retry(self):
        """写入边界失败须递增重试预算（code-review item 9cdd0d2fe972）：边界
        文案内嵌不可信产物内容（本例 repairs path 回显 "429"/"rate limit"/
        "quota" 词形），不传 content_failure=True 会被文本指纹误判 infra——
        不递增 _review_attempts、只计熔断，确定性格式缺陷陷入无预算约束的
        重派循环。与兄弟通道（硬门/读取失败/未知 status）对齐恒归 content。"""
        _mk_project(self.tmpdir)
        mgr, sm, engine = self._manager()
        _write_result(self.tmpdir, "spec", {
            "status": "repaired",
            "repairs": [{"path": "core/429 rate limit quota.txt", "summary": "x"}],
        })
        mgr.consume_review_result("spec")
        entry = sm.read_one("spec")
        # content 语义：尝试预算递增且保持 reviewing 重试（误判 infra 则为 0）
        self.assertEqual(int(entry.get("_review_attempts", 0)), 1)
        self.assertEqual(entry["status"], "reviewing")
        self.assertIsNone(entry.get("reviewer_run"))
        self.assertTrue(
            str(entry.get("error", "")).startswith("spec-review-incomplete:")
        )


class TestReReviewConditions(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _blocked_spec(self, error="spec-review-rejected: 方向性错误"):
        sm = _mk_project(self.tmpdir)
        sm.update_spec("spec", {"status": "blocked", "error": error, "reviewer_run": None})
        mgr, _, _ = self._manager(sm)
        return mgr, sm

    def _manager(self, sm=None):
        sm = sm or _mk_project(self.tmpdir)
        runner = _FakeRunner()
        engine = MagicMock()
        engine.is_review_in_flight = MagicMock(return_value=False)
        return SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock()), sm, engine

    def test_non_review_blocked_rejected(self):
        mgr, sm = self._blocked_spec(error="merge-breaker: 熔断")
        ok, msg = mgr.re_review("spec")
        self.assertFalse(ok)
        self.assertEqual(sm.read_one("spec")["status"], "blocked")

    def test_frozen_rejected(self):
        mgr, sm = self._blocked_spec()
        sm.update_spec("spec", {"frozen": True})
        ok, msg = mgr.re_review("spec")
        self.assertFalse(ok)
        self.assertTrue(sm.read_one("spec")["frozen"])
        self.assertEqual(sm.read_one("spec")["status"], "blocked")

    def test_non_blocked_rejected(self):
        mgr, sm, _ = self._manager()
        sm.update_spec("spec", {"status": "ready"})
        ok, msg = mgr.re_review("spec")
        self.assertFalse(ok)
        self.assertEqual(sm.read_one("spec")["status"], "ready")

    def test_valid_review_blocked_succeeds(self):
        mgr, sm = self._blocked_spec()
        ok, msg = mgr.re_review("spec")
        self.assertTrue(ok)
        self.assertEqual(sm.read_one("spec")["status"], "reviewing")

    def test_frozen_format_error_accepted(self):
        """冻结格式（标记位于中段）的评审 blocked 残留可走重评（code-review
        item 8fdc700aaec1）：现行冻结站点 error 形如「评审否决冻结：原状态
        reviewing · spec-review-rejected: …」（中文前缀开头、评审标记在中段），
        冻结标记被外部抹掉而 status 仍 blocked 时 startswith 判定恒 False，
        重评恢复通道失联——判定放宽为子串包含。"""
        mgr, sm = self._blocked_spec(
            error=(
                f"{REVIEW_REJECTED_FREEZE_ERROR_PREFIX}原状态 reviewing · "
                "spec-review-rejected: 方向性错误"
            )
        )
        ok, msg = mgr.re_review("spec")
        self.assertTrue(ok, msg)
        self.assertEqual(sm.read_one("spec")["status"], "reviewing")

    def test_idempotent_defense(self):
        """Second invoke after first success rejected (status no longer blocked)."""
        mgr, sm = self._blocked_spec()
        ok1, _ = mgr.re_review("spec")
        self.assertTrue(ok1)
        ok2, msg = mgr.re_review("spec")
        self.assertFalse(ok2)


class TestWriteBoundary(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _manager(self):
        sm = _mk_project(self.tmpdir)
        runner = _FakeRunner()
        engine = MagicMock()
        engine.is_review_in_flight = MagicMock(return_value=False)
        return SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock()), sm

    def test_repairs_path_outside_rejected(self):
        """repairs path outside spec dir → boundary violation."""
        mgr, _ = self._manager()
        data = {"status": "repaired",
                "repairs": [{"path": "core/state_machine.py", "summary": "x"}]}
        err = mgr._check_write_boundary("spec", data)
        self.assertIsNotNone(err)
        self.assertIn("越界", err)

    def test_approved_with_changes_rejected(self):
        """approved with non-empty repairs → inconsistent."""
        mgr, _ = self._manager()
        data = {"status": "approved",
                "repairs": [{"path": "spec/changes/spec/tasks.md", "summary": "x"}]}
        err = mgr._check_write_boundary("spec", data)
        self.assertIsNotNone(err)
        self.assertIn("approved", err)

    def test_repaired_without_repairs_rejected(self):
        mgr, _ = self._manager()
        data = {"status": "repaired", "repairs": []}
        err = mgr._check_write_boundary("spec", data)
        self.assertIsNotNone(err)
        self.assertIn("repaired", err)

    # ── 非归因信号不得判越界（2026-09-14 三连评审事故回归）────────────
    #
    # 评审 run 阻塞数分钟，期间主树的并发写者（人工编辑 / 其他会话）会改动
    # 既存脏文件、新建文件。快照比对若把这类变动当越界，评审结果被整轮丢弃，
    # 且 daemon 反复重派直到尝试耗尽——evo-item-retention-doc-tracking 三份
    # 结果（约 $25）全部因此作废。可归因的硬门只剩「SPEC 目录内文件被删除」、
    # 「repairs 路径非法」与「status 与改动不一致」。

    def test_preexisting_dirty_file_modified_not_flagged(self):
        """评审窗口内既存脏文件被并发改动 → 放行。"""
        mgr, _ = self._manager()
        dirty = self.tmpdir / "core" / "dirty.py"
        dirty.parent.mkdir(parents=True, exist_ok=True)
        dirty.write_text("v1\n", encoding="utf-8")
        snapshot = {"spec_files": {},
                    "dirty_files": {"core/dirty.py":
                                    hashlib.md5(dirty.read_bytes()).hexdigest()}}
        dirty.write_text("v2\n", encoding="utf-8")   # 并发写者
        self.assertIsNone(mgr._verify_snapshot("spec", snapshot))

    def test_new_untracked_file_outside_spec_not_flagged(self):
        """评审窗口内主树新建未跟踪文件 → 放行。"""
        mgr, _ = self._manager()
        subprocess.run(["git", "init", "-q"], cwd=self.tmpdir, check=True)
        snapshot = {"spec_files": {}, "dirty_files": {}}
        (self.tmpdir / "core").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "core" / "brand_new.py").write_text("x\n", encoding="utf-8")
        self.assertIsNone(mgr._verify_snapshot("spec", snapshot))

    def test_spec_file_deleted_still_flagged(self):
        """SPEC 目录内文件被删除仍为硬门（评审者只可修补、不可删除）。"""
        mgr, _ = self._manager()
        snapshot = {"spec_files": {"spec/changes/spec/design.md": "deadbeef"},
                    "dirty_files": {}}
        err = mgr._verify_snapshot("spec", snapshot)
        self.assertIsNotNone(err)
        self.assertIn("被删除", err)


class _RecordingRunner:
    """FakeRunner：记录 run 启动那一刻的 STATE，并可选写结果文件 / 触达回调。

    用于回归「锚点在 run 启动前落盘」与「run 收工后机械收口」两处契约。
    """

    def __init__(self, sm, tmpdir, result=None, gate_err=None, success=True, on_run=None):
        self.sm = sm
        self.tmpdir = tmpdir
        self.result = result
        self.gate_err = gate_err
        self.success = success
        self.on_run = on_run
        self.run_id_seen = None
        self.reviewer_run_at_start = None

    def _check_agent_result_artifact(self, spec_name, agent_type,
                                     run_started_at=None, wt_path=None):
        return self.gate_err

    def run_spec_review(self, spec_name, run_id=None):
        # run 启动那一刻的 STATE 快照——锚点必须在此时已落盘
        self.run_id_seen = run_id
        self.reviewer_run_at_start = (self.sm.read_one(spec_name) or {}).get("reviewer_run")
        if self.on_run is not None:
            self.on_run()
        if self.result is not None:
            _write_result(self.tmpdir, spec_name, self.result)
        return MagicMock(success=self.success, run_id=run_id,
                         error=None if self.success else "boom")


class TestDispatchAnchorAndConsume(unittest.TestCase):
    """dispatch_review 接线回归：锚点先落盘（防重派窗口）+ run 收工后机械收口。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fresh(self):
        sm = _mk_project(self.tmpdir)
        sm.update_spec("spec", {"reviewer_run": None})
        return sm

    def test_anchor_written_before_run_starts(self):
        """回归（双派发）：run 启动那一刻 reviewer_run 必须已非空且等于本 run。"""
        sm = self._fresh()
        runner = _RecordingRunner(sm, self.tmpdir, result={"status": "approved", "repairs": []})
        mgr = SpecReviewManager(self.tmpdir, sm, runner, _stub_pm(), {}, MagicMock())
        self.assertTrue(mgr.dispatch_review("spec"))
        self.assertIsNotNone(runner.reviewer_run_at_start)
        self.assertEqual(runner.reviewer_run_at_start, runner.run_id_seen)

    def test_second_dispatch_rejected_while_inflight(self):
        """回归（双派发）：run 在飞期间（锚点已落）第二条派发通道必须被拒。"""
        sm = self._fresh()
        seen = {}
        holder = {}

        def during():
            seen["second"] = holder["mgr"].dispatch_review("spec")

        runner = _RecordingRunner(sm, self.tmpdir,
                                  result={"status": "approved", "repairs": []}, on_run=during)
        mgr = SpecReviewManager(self.tmpdir, sm, runner, _stub_pm(), {}, MagicMock())
        holder["mgr"] = mgr
        self.assertTrue(mgr.dispatch_review("spec"))
        self.assertFalse(seen["second"])

    def test_repaired_result_consumed_to_ready(self):
        """根因回归：run 收工后结果必须被消费（repaired → ready + 派发实现）。

        d012f86680b9 写入边界硬门：repairs 须指向实际被修改的文件，故 run
        期间真实改动修补目标后方可按 repaired 收口（原装置未触碰文件，属
        硬门要拦的「虚假修补」形态）。
        """
        sm = self._fresh()
        engine = MagicMock()
        engine.is_review_in_flight = MagicMock(return_value=False)
        repair_target = Path(self.tmpdir) / "spec" / "changes" / "spec" / "tasks.md"

        def apply_repair():
            repair_target.write_text(
                repair_target.read_text(encoding="utf-8") + "\n<!-- repaired -->\n",
                encoding="utf-8",
            )

        runner = _RecordingRunner(sm, self.tmpdir, result={
            "status": "repaired",
            "repairs": [{"path": "spec/changes/spec/tasks.md", "summary": "x"}]},
            on_run=apply_repair)
        mgr = SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock())
        self.assertTrue(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "ready")
        self.assertIsNone(entry.get("reviewer_run"))
        engine._on_spec_ready.assert_called_once_with("spec")

    def test_rejected_result_consumed_to_blocked(self):
        """根因回归：rejected 结果必须被消费（→ blocked + 规范前缀）。

        fix-spec-review-blocking-dispatch 改造：rejected 未达上限不再递归
        dispatch_review（同步触发二次否决达上限），故需预置 `_review_rejections`
        到上限前一步，使本次消费即达上限触发冻结（原递归路径的等价状态）。
        """
        sm = self._fresh()
        sm.update_spec("spec", {"_review_rejections": MAX_REJECT_REDO - 1})
        engine = MagicMock()
        engine.is_review_in_flight = MagicMock(return_value=False)
        runner = _RecordingRunner(sm, self.tmpdir, result={
            "status": "rejected",
            "findings": [{"severity": "blocking", "aspect": "hole", "detail": "x"}]})
        mgr = SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock())
        self.assertTrue(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "blocked")
        # fix-blocked-freeze-classification 2.1：冻结转人工（frozen=True + 原状态）
        self.assertIs(entry.get("frozen"), True)
        err = str(entry.get("error", ""))
        self.assertIn("spec-review-rejected:", err)
        self.assertIn("原状态 reviewing", err)

    def test_run_failure_clears_anchor_and_counts_attempt(self):
        """run 执行失败：锚点清空、保持 reviewing、尝试计数递增（可重试）。"""
        sm = self._fresh()
        runner = _RecordingRunner(sm, self.tmpdir, success=False)
        mgr = SpecReviewManager(self.tmpdir, sm, runner, _stub_pm(), {}, MagicMock())
        self.assertFalse(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertIsNone(entry.get("reviewer_run"))
        self.assertEqual(entry["status"], "reviewing")
        self.assertEqual(int(entry.get("_review_attempts", 0)), 1)

    def test_exhausted_attempts_blocks_not_stranded(self):
        """尝试耗尽：不得停在 reviewing 空转，须转 blocked（规范前缀）。"""
        sm = self._fresh()
        sm.update_spec("spec", {"_review_attempts": MAX_REVIEW_ATTEMPTS})
        runner = _RecordingRunner(sm, self.tmpdir, result={"status": "approved", "repairs": []})
        mgr = SpecReviewManager(self.tmpdir, sm, runner, _stub_pm(), {}, MagicMock())
        self.assertFalse(mgr.dispatch_review("spec"))
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "blocked")
        # fix-blocked-freeze-classification 2.2：冻结转人工
        self.assertIs(entry.get("frozen"), True)
        err = str(entry.get("error", ""))
        self.assertIn("spec-review-incomplete:", err)
        self.assertIn("原状态 reviewing", err)


class TestArtifactFirstNoReentry(unittest.TestCase):
    """防回退（evo-run-failure-artifact-first 2.4）：
    产物优先分支 consume 后不得重派、不得重复消费。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fresh(self):
        sm = _mk_project(self.tmpdir)
        sm.update_spec("spec", {"reviewer_run": None})
        return sm

    def test_artifact_first_no_redispatch_after_consume(self):
        """产物优先分支 consume 后不得重派：run 只执行一次、状态 ready。"""
        sm = self._fresh()
        calls = []

        def during():
            calls.append("run")

        runner = _RecordingRunner(
            sm, self.tmpdir,
            result={"status": "approved", "repairs": [], "findings": []},
            success=False, on_run=during)
        engine = MagicMock()
        engine.is_review_in_flight = MagicMock(return_value=False)
        mgr = SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock())
        self.assertTrue(mgr.dispatch_review("spec"))
        # run 只执行一次：消费后不得再次派发
        self.assertEqual(len(calls), 1)
        entry = sm.read_one("spec")
        self.assertEqual(entry["status"], "ready")
        self.assertIsNone(entry.get("reviewer_run"))
        engine._on_spec_ready.assert_called_once_with("spec")

    def test_artifact_first_consume_idempotent(self):
        """产物优先分支消费幂等：reviewer_run 清空后重复 consume 不再动作。"""
        sm = self._fresh()
        runner = _RecordingRunner(
            sm, self.tmpdir,
            result={"status": "approved", "repairs": [], "findings": []},
            success=False)
        engine = MagicMock()
        engine.is_review_in_flight = MagicMock(return_value=False)
        mgr = SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock())
        self.assertTrue(mgr.dispatch_review("spec"))
        self.assertEqual(sm.read_one("spec")["status"], "ready")
        # 第二次 consume：reviewer_run 已清空 → 返回 False，状态不变、不重派
        ok2 = mgr.consume_review_result("spec")
        self.assertFalse(ok2)
        self.assertEqual(sm.read_one("spec")["status"], "ready")
        engine._on_spec_ready.assert_called_once_with("spec")


class _FailingReviewRunner:
    """恒失败评审 runner：错误文本/结构化字段可注入（infra 分类构造用）。"""

    def __init__(self, error="Rate limit exceeded", attrs=None):
        self.error = error
        self.attrs = attrs or {}

    def _check_agent_result_artifact(self, spec_name, agent_type,
                                     run_started_at=None, wt_path=None):
        return "结果文件缺失"

    def run_spec_review(self, spec_name, run_id=None):
        return SimpleNamespace(
            success=False, error=self.error, frozen_terminated=False, **self.attrs
        )


class TestBreakerCountSemantics(unittest.TestCase):
    """评审链路熔断计数语义（evo-add-review-failure-attribution 2.2/2.3/3.3）：
    成功收工清零（design D3「链路证明可用」）、失败窗口内连续递增、陈旧跨周
    计数不再误触熔断。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _breaker(self):
        return InfraCircuitBreaker(
            self.tmpdir,
            {"admin": {"run_infra_breaker": {"threshold": 3, "cooldown_minutes": 30}}},
        )

    def _mgr(self, runner, breaker, sm=None):
        sm = sm or _mk_project(self.tmpdir)
        sm.update_spec("spec", {"reviewer_run": None})
        engine = MagicMock()
        engine.is_review_in_flight = MagicMock(return_value=False)
        engine.infra_breaker = breaker
        mgr = SpecReviewManager(self.tmpdir, sm, runner, engine, {}, MagicMock())
        return mgr, sm

    def _ok_runner(self, sm):
        return _RecordingRunner(sm, self.tmpdir, result={"status": "approved", "repairs": []})

    def test_success_run_resets_infra_counter(self):
        """run 跑通即清零：count 归零、state closed（2.2 接线）。"""
        breaker = self._breaker()
        breaker.record_failure("spec-review")
        breaker.record_failure("spec-review")
        self.assertEqual(breaker.get_state("spec-review")["count"], 2)
        sm = _mk_project(self.tmpdir)
        mgr, _ = self._mgr(self._ok_runner(sm), breaker, sm)
        self.assertTrue(mgr.dispatch_review("spec"))
        st = breaker.get_state("spec-review")
        self.assertEqual(st["count"], 0)
        self.assertEqual(st["state"], "closed")

    def test_content_retry_after_run_ok_keeps_counter_zeroed(self):
        """run 跑通但产物不合法走 content 重试：infra 计数已清零且不回增
        （design D3：产物质量类失败不影响 infra 计数）。

        产物不合法用白名单外 status 构造（gate 桩返回 None 走真实解析路径；
        gate_err 与已落盘合法产物的桩组合会人为造出 artifact↔consume 循环，
        生产侧两判定同源不分叉）。
        """
        breaker = self._breaker()
        breaker.record_failure("spec-review")
        sm = _mk_project(self.tmpdir)
        runner = _RecordingRunner(sm, self.tmpdir, result={"status": "bogus"})
        mgr, sm = self._mgr(runner, breaker, sm)
        self.assertTrue(mgr.dispatch_review("spec"))
        self.assertEqual(int(sm.read_one("spec").get("_review_attempts", 0)), 1,
                         "产物不合法须走 content 重试（attempts 递增）")
        st = breaker.get_state("spec-review")
        self.assertEqual(st["count"], 0, "content 类失败不得回增 infra 计数")
        self.assertEqual(st["state"], "closed")

    def test_infra_failures_increment_within_window(self):
        """失败后窗口内连续计数递增：1→2，未达阈值不熔断。"""
        breaker = self._breaker()
        runner = _FailingReviewRunner()
        mgr, sm = self._mgr(runner, breaker)
        self.assertFalse(mgr.dispatch_review("spec"))
        self.assertEqual(breaker.get_state("spec-review")["count"], 1)
        sm.update_spec("spec", {"reviewer_run": None})
        self.assertFalse(mgr.dispatch_review("spec"))
        self.assertEqual(breaker.get_state("spec-review")["count"], 2)
        self.assertFalse(breaker.is_open("spec-review"))

    def test_stale_crossweek_counter_not_false_tripped(self):
        """陈旧跨周计数不再误触（spec Scenario）：上周残留计数 2 → 首次成功
        收工清零 → 偶发 1 次失败从 0 起算，不触发熔断。"""
        breaker = self._breaker()
        breaker.record_failure("spec-review")
        breaker.record_failure("spec-review")
        self.assertEqual(breaker.get_state("spec-review")["count"], 2)
        sm = _mk_project(self.tmpdir)
        mgr, _ = self._mgr(self._ok_runner(sm), breaker, sm)
        self.assertTrue(mgr.dispatch_review("spec"))
        self.assertEqual(breaker.get_state("spec-review")["count"], 0)
        # 清掉首次成功派发落盘的结果文件（陈旧残留会把 artifact 判定与
        # gate 新鲜度门劈开成环——测试桩组合的人工分叉，非生产形态）
        result_file = (
            self.tmpdir / ".fenix" / "spec-review" / "spec" / ".fenix-run-result.json"
        )
        if result_file.exists():
            result_file.unlink()
        sm.update_spec("spec", {"status": "reviewing", "reviewer_run": None})
        mgr2, _ = self._mgr(_FailingReviewRunner(), breaker, sm)
        self.assertFalse(mgr2.dispatch_review("spec"))
        st = breaker.get_state("spec-review")
        self.assertEqual(st["count"], 1)
        self.assertFalse(breaker.is_open("spec-review"))

    def test_recovery_first_dispatch_success_resets_half_open_count(self):
        """2.3 确认路径：冷却到期恢复后首次派发成功 → record_success 清零
        半开残留计数（condition 恢复时 count 保留，靠成功路径清零）。"""
        breaker = self._breaker()
        for _ in range(3):
            breaker.record_failure("spec-review")
        self.assertTrue(breaker.is_open("spec-review"))
        with breaker._lock:
            breaker._cache["spec-review"]["until"] = time.time() - 1
        self.assertEqual(breaker.condition("spec-review"), "recovered")
        self.assertEqual(breaker.get_state("spec-review")["count"], 3,
                         "半开探测语义：恢复时 count 保留")
        sm = _mk_project(self.tmpdir)
        mgr, _ = self._mgr(self._ok_runner(sm), breaker, sm)
        self.assertTrue(mgr.dispatch_review("spec"))
        st = breaker.get_state("spec-review")
        self.assertEqual(st["count"], 0, "冷却到期后首次派发成功须清零残留计数")
        self.assertEqual(st["state"], "closed")

    def test_breaker_shortcircuit_dispatch_counts_nothing(self):
        """熔断短路期间未实际派发的尝试不计成功/失败：dispatch 入口直接返回，
        计数与熔断窗口不动（2.3）。"""
        breaker = self._breaker()
        for _ in range(3):
            breaker.record_failure("spec-review")
        before = breaker.get_state("spec-review")
        sm = _mk_project(self.tmpdir)
        ran = []

        class _ProbeRunner(_FailingReviewRunner):
            def run_spec_review(self, spec_name, run_id=None):
                ran.append(run_id)
                return super().run_spec_review(spec_name, run_id=run_id)

        mgr, _ = self._mgr(_ProbeRunner(), breaker, sm)
        self.assertFalse(mgr.dispatch_review("spec"))
        self.assertEqual(ran, [], "熔断窗口内 MUST NOT 实际派发")
        self.assertEqual(breaker.get_state("spec-review"), before)


if __name__ == "__main__":
    unittest.main()
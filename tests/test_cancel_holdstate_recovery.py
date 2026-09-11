"""fix-cancel-holdstate-recovery 单测：人工取消 hold-state 的持久化、恢复尊重、
显式复位解锁与监测豁免。

覆盖：
- 六处取消收尾分支写入 _cancelled_hold 标记且不改既有取消语义（任务 1.3）
- recover_interrupted 遇标记跳过复位/重派/重启重验计数，无标记回归不变（任务 2.2）
- update_spec 显式携带 status 清标记、仅 error 隐式更新不清（任务 3.2）
- admin_monitor._detect_stuck 对保持态豁免，无标记回归不变（任务 4.2）
"""
import json
import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine, VERIFY_REDO_COUNT_FIELD


CANCEL_ERR = "run 被人工取消：测试原因"


def _mk_sm(tmpdir: str) -> StateMachine:
    proot = Path(tmpdir)
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    return StateMachine(proot / ".fenix" / "STATE.md", MagicMock())


def _mk_hold_spec(sm: StateMachine, name: str = "s1", status: str = "implementing",
                  err: str = CANCEL_ERR) -> dict:
    """构造一个处于取消保持态的 spec（status 停留 + error 取消文案 + 标记）。"""
    sm.add_spec(name, {"priority": 5})
    if status != "drafted":
        sm.transition(name, "ready")
        sm.transition(name, "implementing")
        if status == "testing":
            sm.transition(name, "implemented")
            sm.transition(name, "testing")
    sm.update_spec(name, {"error": err, "_cancelled_hold": True})
    return sm.read_one(name)


def _stale(sm: StateMachine, name: str, hours: float = 3.0) -> None:
    """把 spec 的 updated 改为 hours 小时前（模拟取消后长时间无进度）。"""
    specs = sm.read_all()
    specs[name]["updated"] = (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).isoformat()
    sm.write_all(specs)


# ── 1. 取消收尾写入持久标记 ──────────────────────────────────

class CancelFinalizeMarkerContract(unittest.TestCase):
    """取消收尾分支 update_spec 调用必须携带 _cancelled_hold=True。

    六处收尾分支形态各异（缩进/上下文不同），静态钉六处写点：
    对每处断言其 update_spec 调用字典含 "_cancelled_hold": True 键，
    且紧邻的 error 键在同一个调用内（同层写入，逐字段一致契约）。
    """

    WRITE_POINTS = [
        # 2026-09-11 零变更哨确认型 no-op 放行通道在 dispatch.py 前部插入 24 行，
        # implementer/fast-track/repair 写点整体后移（原 981/1817/2275 → 现
        # 1005/1841/2299），写点语义不变。
        ("core/pm_engine/dispatch.py", 1005, "implementer"),
        ("core/pm_engine/dispatch.py", 1841, "fast-track"),
        ("core/pm_engine/dispatch.py", 2299, "repair"),
        # add-verify-parallel-backoff 在 verification.py 插入降档读写后行号
        # 整体后移（原 1431/1742/2515 → 现 1451/1781/2560），写点语义不变。
        ("core/pm_engine/verification.py", 1451, "planner-plan"),
        ("core/pm_engine/verification.py", 1781, "planner-judge"),
        ("core/pm_engine/verification.py", 2560, "legacy-verifier"),
    ]

    def _load(self, rel: str) -> list:
        text = (Path(__file__).resolve().parent.parent / rel).read_text("utf-8")
        return text.splitlines()

    def test_six_holdstate_write_points_carry_marker(self):
        for rel, line_no, label in self.WRITE_POINTS:
            with self.subTest(label=label):
                lines = self._load(rel)
                # 以写点行号为中心的邻域内必须出现 _cancelled_hold 标记
                window = lines[line_no - 8: line_no + 6]
                self.assertTrue(
                    any('"_cancelled_hold": True' in ln for ln in window),
                    f"{rel}:{line_no} ({label}) 缺少 _cancelled_hold 写入",
                )
                # 同一调用字典内 error 与标记同层：邻域内两键都在
                self.assertTrue(
                    any('"error": cancelled_err' in ln for ln in window),
                    f"{rel}:{line_no} ({label}) error 写点漂移，请核对行号",
                )

    def test_no_new_holdstate_write_point_missed(self):
        """全库 hold-state 收尾写点只有六处（未来新增 run 类型会在此失败）。"""
        root = Path(__file__).resolve().parent.parent / "core"
        hits = []
        for py in root.rglob("*.py"):
            text = py.read_text("utf-8")
            if "hold-state" in text and "人工取消" in text:
                hits.append(str(py.relative_to(root.parent)))
        self.assertEqual(sorted(hits), sorted({rel for rel, _, _ in self.WRITE_POINTS}))


# ── 2. 重启恢复尊重保持 ──────────────────────────────────────

class TestRecoverInterruptedRespectsHold(unittest.TestCase):
    """recover_interrupted 遇 _cancelled_hold 跳过：不复位、不重派、不计数。"""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.sm = _mk_sm(self.tmpdir)

    def tearDown(self):
        import shutil
        import shutil as _shutil
        import shutil as _s
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_implementing_hold_survives_restart(self):
        entry0 = _mk_hold_spec(self.sm, "s1", "implementing")
        before = dict(entry0)
        recovered = self.sm.recover_interrupted()
        self.assertEqual(recovered, [])
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implementing")
        self.assertEqual(entry["error"], before["error"])
        self.assertTrue(entry["_cancelled_hold"])
        self.assertEqual(entry["implementer_run"], before["implementer_run"])
        self.assertEqual(entry["branch"], before["branch"])
        # 无 Recovered 改写
        self.assertNotIn("Recovered from interrupted state", entry["error"])
        # 重启重验计数不动
        self.assertEqual(entry.get(VERIFY_REDO_COUNT_FIELD, 0), 0)

    def test_testing_hold_survives_restart_and_no_redo_count(self):
        _mk_hold_spec(self.sm, "s2", "testing")
        recovered = self.sm.recover_interrupted()
        self.assertEqual(recovered, [])
        entry = self.sm.read_one("s2")
        self.assertEqual(entry["status"], "testing")
        self.assertEqual(entry["error"], CANCEL_ERR)
        self.assertTrue(entry["_cancelled_hold"])
        self.assertEqual(entry.get(VERIFY_REDO_COUNT_FIELD, 0), 0)

    def test_unmarked_implementing_recovery_regression(self):
        """无标记 implementing spec：恢复行为与现状一致（复位 ready + Recovered + run 清空）。"""
        self.sm.add_spec("s3", {"priority": 5})
        self.sm.transition("s3", "ready")
        self.sm.transition("s3", "implementing")
        self.sm.update_spec("s3", {"error": "进程被杀"})
        recovered = self.sm.recover_interrupted()
        self.assertIn("s3", recovered)
        entry = self.sm.read_one("s3")
        self.assertEqual(entry["status"], "ready")
        self.assertEqual(
            entry["error"], "Recovered from interrupted state: implementing")
        self.assertIsNone(entry["implementer_run"])
        self.assertFalse(entry.get("_cancelled_hold", False))

    def test_unmarked_testing_recovery_regression(self):
        """无标记 testing spec：重验计数递增 + 复位 implemented（现状回归）。"""
        self.sm.add_spec("s4", {"priority": 5})
        self.sm.transition("s4", "ready")
        self.sm.transition("s4", "implementing")
        self.sm.transition("s4", "implemented")
        self.sm.transition("s4", "testing")
        self.sm.update_spec("s4", {"error": "验证进程被杀"})
        recovered = self.sm.recover_interrupted()
        self.assertIn("s4", recovered)
        entry = self.sm.read_one("s4")
        self.assertEqual(entry["status"], "implemented")
        # 代码库惯例：STATE.md 内部计数字段为字符串格式，读侧 int() 强转
        self.assertEqual(int(entry.get(VERIFY_REDO_COUNT_FIELD) or 0), 1)


# ── 3. 显式复位解锁 ─────────────────────────────────────────

class TestExplicitResetUnlocks(unittest.TestCase):
    """update_spec 显式携带 status 清除标记；仅 error 隐式更新不清。"""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.sm = _mk_sm(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_explicit_status_reset_clears_marker(self):
        _mk_hold_spec(self.sm, "s1", "implementing")
        self.sm.update_spec("s1", {"status": "ready"})
        entry = self.sm.read_one("s1")
        self.assertFalse(entry["_cancelled_hold"])
        # 清除后恢复链路恢复正常路径
        recovered = self.sm.recover_interrupted()
        self.assertEqual(recovered, [])  # ready 非 INTERRUPTED_STATES，无需恢复

    def test_explicit_reset_then_recovery_normal(self):
        _mk_hold_spec(self.sm, "s1", "implementing")
        self.sm.update_spec("s1", {"status": "implementing"})
        # 显式重写 status（如 admin 处置重派）也解锁；再制造中断态验证恢复不再跳过
        self.assertFalse(self.sm.read_one("s1")["_cancelled_hold"])
        recovered = self.sm.recover_interrupted()
        self.assertIn("s1", recovered)
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")

    def test_error_only_update_keeps_marker(self):
        _mk_hold_spec(self.sm, "s1", "implementing")
        self.sm.update_spec("s1", {"error": "补充说明"})
        entry = self.sm.read_one("s1")
        self.assertTrue(entry["_cancelled_hold"])
        self.assertEqual(entry["status"], "implementing")

    def test_transition_also_unlocks(self):
        """transition 底层走 update_spec（携带 status），同样解锁。"""
        _mk_hold_spec(self.sm, "s1", "implementing")
        self.sm.transition("s1", "implemented")
        self.assertFalse(self.sm.read_one("s1")["_cancelled_hold"])


# ── 4. 监测豁免 ──────────────────────────────────────────────

class _FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs


class _FakeLogger:
    def warning(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def _mk_monitor(tmp_path: Path, specs: dict):
    from core.admin_monitor import AdminMonitor
    from core.admin_store import AdminStore
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    mon = AdminMonitor(
        {},
        _FakeSM(specs),
        proot,
        _FakeLogger(),
        store=AdminStore(proot, _FakeLogger()),
        agent_runner=None,
    )
    return proot, mon


class TestMonitorExemptsHold(unittest.TestCase):
    """_detect_stuck 对 _cancelled_hold spec 豁免；无标记回归不变。"""

    def test_hold_spec_not_stuck(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            _, mon = _mk_monitor(tmp, {
                "spec-hold": {
                    "status": "implementing",
                    "updated": (datetime.now(timezone.utc) - timedelta(minutes=200)).isoformat(),
                    "_cancelled_hold": True,
                },
            })
            signals = mon.run_once()
            self.assertEqual([s for s in signals if s["signal_type"] == "stuck"], [])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_hold_spec_testing_not_stuck(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            _, mon = _mk_monitor(tmp, {
                "spec-hold2": {
                    "status": "testing",
                    "updated": (datetime.now(timezone.utc) - timedelta(minutes=200)).isoformat(),
                    "_cancelled_hold": True,
                },
            })
            signals = mon.run_once()
            self.assertEqual([s for s in signals if s["signal_type"] == "stuck"], [])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unmarked_stuck_regression(self):
        """无标记 spec：stuck 检测回归不变（仍产生信号）。"""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            _, mon = _mk_monitor(tmp, {
                "spec-a": {
                    "status": "implementing",
                    "updated": (datetime.now(timezone.utc) - timedelta(minutes=200)).isoformat(),
                },
            })
            signals = mon.run_once()
            self.assertTrue(any(s["signal_type"] == "stuck" for s in signals))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# ── 六处收尾行为级单测（夹具 run 取消收尾 → 标记 + 语义一致） ──────────

class _CancelledResult:
    """模拟被人工取消的 run 结果对象（与 AgentRunResult 取消字段同形）。"""

    def __init__(self, error="测试原因"):
        self.success = False
        self.cancelled = True
        self.error = error
        self.run_id = "r-test"
        self.branch = None
        self.chain_exhausted = False
        self.worktree_dirty = None
        self.duration_seconds = 1.0


class TestCancelFinalizeSemantics(unittest.TestCase):
    """fast-track / verification 取消收尾路径的行为级验证。

    implementer 取消分支位于 _run_agent_worker 的 implementer 大分支内
    （run_implementer 全内联，无独立 flow 方法），其前置副作用（worktree
    派发、ensure_spec_committed）无法在单测内轻量触达，标记写入由
    CancelFinalizeMarkerContract 静态钉住；此处行为级验证 fast-track 与
    verification 收尾分支（独立方法，可直接触达）。
    """

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir()
        self.logger = MagicMock()
        self.state_path = self.project_root / ".fenix" / "STATE.md"
        self.sm = StateMachine(self.state_path, self.logger)
        from core.pm_engine import PMEngine
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.project_root, self.logger)
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")
        self.sm.transition("s1", "implementing")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _assert_cancel_semantics(self, entry: dict):
        self.assertEqual(entry["status"], "implementing")
        self.assertEqual(entry["error"], "run 被人工取消：测试原因")
        self.assertTrue(entry["_cancelled_hold"])
        # 不动计数（取消语义：_retry_count/_merge_streak 原样）
        self.assertEqual(int(entry.get("_retry_count") or 0), 0)
        self.assertEqual(int(entry.get("_merge_streak") or 0), 0)

    def test_fast_track_cancel_finalizes_with_marker(self):
        self.engine._dispatcher._run_fast_track_flow(
            "s1", _CancelledResult())
        self._assert_cancel_semantics(self.sm.read_one("s1"))

    def test_verification_planner_cancel_keeps_testing_with_marker(self):
        self.sm.transition("s1", "implemented")
        self.sm.transition("s1", "testing")
        result = _CancelledResult()
        with patch("importlib.reload", lambda m: m), \
                patch.object(self.engine.agent_runner, "run_planner",
                             return_value=result):
            # 三阶段验证阶段1：planner 取消分支保持 testing、只写 error+标记。
            # patch importlib.reload（test_pm_verification 同款处方）：
            # _run_three_stage_verification 开头对 core.verify_engine 热重载，
            # 测试进程里 reload 会换掉 TestScenario/VerifyEngine 类对象，
            # 同进程后续测试的 isinstance 判定全部失配（全量跑时
            # test_verify_multi_kind 的 TestEngineDispatch 非确定性 0 场景假败）。
            self.engine._run_three_stage_verification("s1")
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "testing")
        self.assertEqual(entry["error"], "run 被人工取消：测试原因")
        self.assertTrue(entry["_cancelled_hold"])

    def test_hold_spec_not_stuck_after_finalize(self):
        """取消收尾后 spec 长期滞留也不触发 stuck 自动升级。"""
        result = _CancelledResult()
        self.engine._dispatcher._run_fast_track_flow("s1", result)
        _stale(self.sm, "s1", hours=4)
        from core.admin_monitor import AdminMonitor
        from core.admin_store import AdminStore
        mon = AdminMonitor(
            {}, _FakeSM(self.sm.read_all()), self.project_root, _FakeLogger(),
            store=AdminStore(self.project_root, _FakeLogger()), agent_runner=None)
        signals = mon.run_once()
        self.assertEqual([s for s in signals if s["signal_type"] == "stuck"], [])


if __name__ == "__main__":
    unittest.main()

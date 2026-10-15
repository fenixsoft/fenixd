"""fix-cancel-holdstate-recovery 单测：人工取消 hold-state 的持久化、恢复尊重、
显式复位解锁与监测豁免。

覆盖：
- 取消收尾分支写入 _cancelled_hold 标记且不改既有取消语义（任务 1.3；
  2026-10-12 item 5ee56fc13640 补齐重派 judge 车道后为八处；2026-10-14
  code-review item 04f7f14b2b54 三让位分支收敛 _yield_on_agent_failure
  单源后为七处；2026-10-15 item d2bce687564b plan 车道并入同单源后为六处）
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

    收尾分支形态各异（缩进/上下文不同），静态钉六处写点：
    对每处断言其 update_spec 调用字典含 "_cancelled_hold": True 键，
    且紧邻的 error 键在同一个调用内（同层写入，逐字段一致契约）。

    （2026-10-12 code-review item 5ee56fc13640：重派 judge 车道取消分支补齐
    hold-state 写点，与首次派发路径对齐——写点增至八处，锚点表同步登记。
    2026-10-14 code-review item 04f7f14b2b54：pipeline.py 三让位分支
    （首次派发/重派 judge/fail-closed 重派）收敛 _yield_on_agent_failure
    单源，写点八→七处，锚点表两 judge 条目并为一源条目「三让位单源」。
    2026-10-15 code-review item d2bce687564b：pipeline.py plan 车道取消
    分支并入同一单源，写点七→六处，锚点表 planner-plan 条目移除——其
    取消保持写点由「三让位单源」条目继续覆盖。）

    写点定位使用语义锚点（_locate 按锚点串动态检索），免疫行号漂移：
    历史上写点行号随并行合并三次漂移并手工重钉（14380774 / 2e98e052 /
    762b4aee），当前（2026-09-12）verification.py 三处写点已漂到
    1629/2003/2836 而测试仍钉旧行号导致 3/6 子用例红灯且无人发现——
    锚点方案下失配即红（报错含 label + 锚点串 + 命中情况），无需人工对齐行号。
    """

    # 写点语义锚点表：(rel, anchor, label)。
    # anchor = 写点前向最近、且在其文件内唯一命中的「人工取消
    # hold-state（add-run-cancel D4…）」分支注释字面（grep -F 逐条
    # 核验恰好命中 1 次，唯一性由 _locate 与全库扫描双重自证）。
    # 例外：三让位单源条目的锚点是 _yield_on_agent_failure 的 cancelled
    # 判定行字面（其分支注释随单源收敛删除，code-review 04f7f14b2b54）。
    # 锚点行 → 写点行偏移：implementer +23 / fast-track +20 / repair
    # +19（dispatch.py），三让位单源 +8（verification/
    # pipeline.py），legacy-verifier +17（verification/_legacy.py），
    # reroute-judge +16（verification/escalation.py，code-review
    # 9affa1c31b7c 补齐改道车道取消 hold-state 留痕），全部落在
    # [anchor_line, anchor_line+25) 窗口内（最大偏移 +23，余量仅 2 行，
    # queue.py 写点与锚点距离再拉大即须按报错提示调窗口）。
    WRITE_POINTS = [
        ("core/pm_engine/dispatch/queue.py",
         "人工取消 hold-state（add-run-cancel D4）",
         "implementer"),
        ("core/pm_engine/dispatch/fast_track.py",
         "人工取消 hold-state（add-run-cancel D4，fast-track 同语义）",
         "fast-track"),
        ("core/pm_engine/dispatch/repair_lane.py",
         "人工取消 hold-state（add-run-cancel D4，repair worker）",
         "repair"),
        ("core/pm_engine/verification/pipeline.py",
         'getattr(result, "cancelled", False) is True',
         "三让位单源"),
        ("core/pm_engine/verification/legacy.py",
         "人工取消 hold-state（add-run-cancel D4，legacy verifier）",
         "legacy-verifier"),
        ("core/pm_engine/verification/escalation.py",
         "人工取消 hold-state（与 pipeline.py",
         "reroute-judge"),
    ]
    # 断言窗口：锚点行起向后 WRITE_POINT_WINDOW 行。
    # 覆盖表内最大偏移 +20 并留 5 行余量；若未来某写点与锚点距离拉大
    # 越过窗口，报错会提示窗口大小，按表内偏移调整本常量即可。
    WRITE_POINT_WINDOW = 25

    @staticmethod
    def _load(rel: str) -> list:
        text = (Path(__file__).resolve().parent.parent / rel).read_text("utf-8")
        return text.splitlines()

    @staticmethod
    def _locate(rel: str, anchor: str, label: str) -> int:
        """以锚点串在 rel 中动态定位写点行；未命中/多命中即抛红。

        失配报错内含 rel、label、锚点串原文与当前命中情况，定位即诊断：
        锚点注释被改写/删除 → 0 次命中；锚点串被复用 → >1 次命中需改精确串。
        """
        hits = [i for i, ln in enumerate(
            CancelFinalizeMarkerContract._load(rel), 1) if anchor in ln]
        if not hits:
            raise AssertionError(
                f"{rel} ({label}) 锚点串未命中：{anchor!r}"
                "（注释被改写/删除？）")
        if len(hits) > 1:
            raise AssertionError(
                f"{rel} ({label}) 锚点串命中 {len(hits)} 次：{anchor!r}"
                "（不唯一，请改用更精确串）")
        return hits[0]

    def test_holdstate_write_points_carry_marker(self):
        for rel, anchor, label in self.WRITE_POINTS:
            with self.subTest(label=label):
                lines = self._load(rel)
                anchor_line = self._locate(rel, anchor, label)
                # 锚点行起 +WRITE_POINT_WINDOW 窗口内必须同时出现
                # _cancelled_hold 标记与 error 键（同层写入，逐字段一致契约）。
                window = lines[anchor_line: anchor_line + self.WRITE_POINT_WINDOW]
                self.assertTrue(
                    any('"_cancelled_hold": True' in ln for ln in window),
                    f"{rel} ({label}) 锚点 {anchor!r} 后 "
                    f"{self.WRITE_POINT_WINDOW} 行窗口内缺少 _cancelled_hold 写入"
                    "（写点与锚点距离过大？请调整 WRITE_POINT_WINDOW）",
                )
                self.assertTrue(
                    any('"error": cancelled_err' in ln for ln in window),
                    f"{rel} ({label}) 锚点 {anchor!r} 后 "
                    f"{self.WRITE_POINT_WINDOW} 行窗口内缺少 error 写点"
                    "（写点与锚点距离过大？请调整 WRITE_POINT_WINDOW）",
                )

    def test_no_new_holdstate_write_point_missed(self):
        """全库 hold-state 收尾写点恰好六处，与锚点表条目数/文件集合互为印证。

        与 test_holdstate_write_points_carry_marker 的锚点表并行：
        文件集合一致（无新增/删减文件）+ 写点总数恰好六处（无漏入表）。
        未来新增 run 类型时，此处与锚点表会同时红。
        （基线 8→7：2026-10-14 code-review item 04f7f14b2b54 三让位分支
        收敛 _yield_on_agent_failure 单源，取消保持语义不变。
        基线 7→6：2026-10-15 item d2bce687564b plan 车道并入同一单源，
        取消保持语义不变。）
        """
        root = Path(__file__).resolve().parent.parent / "core"
        hits = {}
        for py in root.rglob("*.py"):
            text = py.read_text("utf-8")
            if "hold-state" in text and "人工取消" in text:
                rel = str(py.relative_to(root.parent))
                # 以 _cancelled_hold 标记写入处数计写点（与锚点表条数同口径）
                hits[rel] = sum(
                    1 for ln in text.splitlines()
                    if '"_cancelled_hold": True' in ln)
        # 文件集合与锚点表一一对应
        self.assertEqual(
            sorted(hits),
            sorted({rel for rel, _, _ in self.WRITE_POINTS}),
            "全库 hold-state 写点文件集合与锚点表不一致",
        )
        # 写点总数恰好六处，与锚点表条目数互为印证
        self.assertEqual(
            sum(hits.values()), 6,
            "全库 _cancelled_hold 写点总数非六处：新增/删除了写点而未同步锚点表",
        )
        self.assertEqual(
            len(self.WRITE_POINTS), 6,
            "锚点表条目数非六处：与全库写点总数不一致",
        )


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


# ── 七处收尾行为级单测（夹具 run 取消收尾 → 标记 + 语义一致） ──────────

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

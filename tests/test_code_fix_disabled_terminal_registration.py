"""test_code_fix_disabled_terminal_registration.py — disabled 终态收口登记测试。

覆盖 evo-add-code-fix-chain-terminal-registration 五形态：

1. 首收口落双登记（告警 + todo，含剩余量/终态原因/触发提示/severity）；
2. disabled 后重复 checkpoint 零新增；
3. 批在飞提示路径只写提示、不登记；
4. 重新触发（进度翻回 running=true）后再次 disabled 落新登记；
5. 登记通道异常时终态仍落盘、checkpoint 返回值不变（fail-open）。

另覆盖剩余条数读台账失败回退进度 ``total-done``（1.2）。
MUST NOT 真跑 agent——fake runner / 临时目录（复用 test_code_fix 夹具）。
"""

import unittest
from pathlib import Path
from unittest import mock

from test_code_fix import (
    _FakeLogger,
    _FakeRunner,
    _item,
    _make_project_root,
    _write_items,
    _write_verify_yaml,
)

SIGNAL_TYPE = "code_fix_disabled_terminal"


class _CapturingExecutor:
    """捕获投递（不执行）：让 _in_flight 保持为真实在飞态。"""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, ctx=None):
        self.jobs.append((fn, (ctx,) if ctx is not None else ()))


def _make_orch(proot):
    from core.code_fix import CodeFixOrchestrator

    cfg = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 20}}}
    runner = _FakeRunner(proot)
    executor = _CapturingExecutor()
    orch = CodeFixOrchestrator(
        runner, proot, config=cfg, logger=_FakeLogger(), executor=executor
    )
    return orch, cfg, runner, executor


def _start_live_chain(proot, n_items=3):
    """投递首批（链 running=true、批在飞），返回来龙去脉的句柄。"""
    _write_items(proot, {k: _item(k) for k in [chr(ord("a") + i) for i in range(n_items)]})
    _write_verify_yaml(proot)
    orch, cfg, runner, executor = _make_orch(proot)
    res = orch.checkpoint()
    assert res.get("triggered"), f"首批未投递: {res}"
    assert executor.jobs, "首批未进入 executor"
    return orch, cfg, runner, executor


def _disable(cfg):
    cfg["admin"]["code_review_fix"]["enabled"] = False


def _simulate_batch_finished(orch):
    """模拟批 worker 收尾（_run_batch finally 清退在飞标记）。"""
    orch._in_flight = False


def _signals(proot):
    from core.admin_store import AdminStore

    return [
        r for r in AdminStore(proot, logger=None).read_all()
        if r.get("signal_type") == SIGNAL_TYPE
    ]


def _todo_text(proot):
    p = Path(proot) / ".fenix" / "todo.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


class TestDisabledTerminalRegistration(unittest.TestCase):
    # ── 形态 1：首收口落双登记 ──────────────────────────────────────
    def test_first_terminal_registers_alert_and_todo(self):
        from core.code_fix import _DISABLED_TERMINAL_TODO_TITLE, read_progress

        proot = _make_project_root()
        orch, cfg, _runner, _executor = _start_live_chain(proot, n_items=3)
        _disable(cfg)
        _simulate_batch_finished(orch)

        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "disabled"})
        prog = read_progress(proot)
        self.assertFalse(prog["running"])
        self.assertEqual(prog["phase"], "blocked")
        self.assertEqual(prog["reason"], "disabled")

        alerts = _signals(proot)
        self.assertEqual(len(alerts), 1, "首收口 MUST 落一条 disabled 终态告警")
        rec = alerts[0]
        self.assertEqual(rec.get("severity"), "warning")
        blob = f"{rec.get('description')} {rec.get('evidence')}"
        self.assertIn("剩余未修复条数=3", blob, "剩余量取实时台账 open 数")
        self.assertIn("自动修复总开关已关闭", blob)
        self.assertIn("POST /api/code-review/fix-run", blob, "缺重新触发入口提示")

        todo = _todo_text(proot)
        self.assertIn(_DISABLED_TERMINAL_TODO_TITLE, todo)
        self.assertIn("剩余未修复条数：3", todo)
        self.assertIn("自动修复总开关已关闭", todo)
        self.assertIn("POST /api/code-review/fix-run", todo)

    # ── 形态 2：disabled 后重复 checkpoint 零新增 ───────────────────
    def test_repeat_checkpoint_does_not_duplicate(self):
        from core.code_fix import _DISABLED_TERMINAL_TODO_TITLE, read_progress

        proot = _make_project_root()
        orch, cfg, _runner, _executor = _start_live_chain(proot)
        _disable(cfg)
        _simulate_batch_finished(orch)
        self.assertEqual(orch.checkpoint(), {"triggered": False, "reason": "disabled"})
        before_prog = read_progress(proot)
        before_alerts = len(_signals(proot))
        before_todo = _todo_text(proot).count(_DISABLED_TERMINAL_TODO_TITLE)
        self.assertEqual(before_alerts, 1)
        self.assertEqual(before_todo, 1)

        for _ in range(3):
            self.assertEqual(
                orch.checkpoint(), {"triggered": False, "reason": "disabled"}
            )
        self.assertEqual(len(_signals(proot)), 1, "同一 disabled 期 MUST NOT 重复告警")
        self.assertEqual(
            _todo_text(proot).count(_DISABLED_TERMINAL_TODO_TITLE), 1,
            "同一 disabled 期 MUST NOT 重复 todo 登记",
        )
        after_prog = read_progress(proot)
        self.assertEqual(after_prog["phase"], before_prog["phase"])
        self.assertEqual(after_prog["reason"], before_prog["reason"])
        self.assertFalse(after_prog["running"])

    # ── 形态 3：批在飞提示路径不登记 ────────────────────────────────
    def test_in_flight_prompt_path_does_not_register(self):
        from core.code_fix import read_progress

        proot = _make_project_root()
        orch, cfg, _runner, _executor = _start_live_chain(proot)
        _disable(cfg)
        # 批仍在飞（_in_flight=True）：checkpoint 只写提示性 current
        self.assertEqual(orch.checkpoint(), {"triggered": False, "reason": "disabled"})
        prog = read_progress(proot)
        self.assertTrue(prog["running"], "在飞提示写点 MUST 保留 running=true")
        self.assertEqual(prog["reason"], "disabled")
        self.assertEqual(_signals(proot), [], "批在飞 MUST NOT 落告警")
        self.assertFalse(
            (Path(proot) / ".fenix" / "todo.md").exists(),
            "批在飞 MUST NOT 落 todo 登记",
        )

    # ── 形态 4：重新触发后再次 disabled 落新登记 ────────────────────
    def test_retrigger_then_disabled_registers_again(self):
        from core.code_fix import (
            _DISABLED_TERMINAL_TODO_TITLE, read_progress, write_progress,
        )

        proot = _make_project_root()
        orch, cfg, _runner, executor = _start_live_chain(proot)
        _disable(cfg)
        _simulate_batch_finished(orch)
        self.assertEqual(orch.checkpoint(), {"triggered": False, "reason": "disabled"})
        self.assertEqual(len(_signals(proot)), 1)
        self.assertEqual(_todo_text(proot).count(_DISABLED_TERMINAL_TODO_TITLE), 1)

        # 人工重新触发（override_enabled 路径）→ 进度翻回 running=true，
        # 去重窗口重置。清除手动授权旗标以模拟授权链收尾后的再次撞墙
        # （真实链的 manual_authorized 随终态清除；此处直接对齐「disabled
        # 守卫命中」所需的前置：running=true 且无链上授权）。
        jobs_before = len(executor.jobs)
        res = orch.checkpoint(override_enabled=True)
        self.assertTrue(res.get("triggered"), f"override 未重新投递: {res}")
        self.assertEqual(len(executor.jobs), jobs_before + 1)
        self.assertTrue(read_progress(proot)["running"])
        write_progress(proot, manual_authorized=False)
        _simulate_batch_finished(orch)

        # 再次撞 disabled 终态 → 必须落新登记（不被旧未处置信号吞掉）
        self.assertEqual(orch.checkpoint(), {"triggered": False, "reason": "disabled"})
        self.assertEqual(
            len(_signals(proot)), 2,
            "重新触发后再次 disabled MUST 落新的一条告警",
        )
        self.assertEqual(
            _todo_text(proot).count(_DISABLED_TERMINAL_TODO_TITLE), 2,
            "重新触发后再次 disabled MUST 落新的一条 todo 登记",
        )

    # ── 形态 5：登记通道异常不阻断终态 ──────────────────────────────
    def test_alert_channel_exception_is_fail_open(self):
        from core.code_fix import _DISABLED_TERMINAL_TODO_TITLE, read_progress

        proot = _make_project_root()
        orch, cfg, _runner, _executor = _start_live_chain(proot)
        _disable(cfg)
        _simulate_batch_finished(orch)
        with mock.patch(
            "core.code_fix._write_disabled_terminal_alert",
            side_effect=RuntimeError("admin store down"),
        ):
            res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "disabled"})
        prog = read_progress(proot)
        self.assertFalse(prog["running"], "告警异常 MUST NOT 回退已落盘终态")
        self.assertEqual(prog["phase"], "blocked")
        self.assertEqual(prog["reason"], "disabled")
        self.assertIn(
            _DISABLED_TERMINAL_TODO_TITLE, _todo_text(proot),
            "告警通道异常不阻断 todo 通道",
        )

    def test_todo_channel_exception_is_fail_open(self):
        from core.code_fix import read_progress

        proot = _make_project_root()
        orch, cfg, _runner, _executor = _start_live_chain(proot)
        _disable(cfg)
        _simulate_batch_finished(orch)
        with mock.patch(
            "core.code_fix._append_disabled_terminal_todo_entry",
            side_effect=OSError("todo locked"),
        ):
            res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "disabled"})
        prog = read_progress(proot)
        self.assertFalse(prog["running"], "todo 异常 MUST NOT 回退已落盘终态")
        self.assertEqual(prog["phase"], "blocked")
        self.assertEqual(prog["reason"], "disabled")
        self.assertEqual(len(_signals(proot)), 1, "todo 通道异常不阻断告警通道")

    # ── 1.2 补充：读台账失败回退进度 total-done ────────────────────
    def test_remaining_falls_back_to_progress_snapshot_on_ledger_error(self):
        from core.code_fix import read_progress, write_progress

        proot = _make_project_root()
        orch, cfg, _runner, _executor = _start_live_chain(proot, n_items=3)
        _disable(cfg)
        _simulate_batch_finished(orch)
        # 进度陈旧快照 total=10 / done=4 → 回退值应为 6（区别于台账 open=3）
        write_progress(proot, total=10, done=4)
        with mock.patch(
            "core.code_fix.read_items", side_effect=OSError("ledger unreadable")
        ):
            res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "disabled"})
        alerts = _signals(proot)
        self.assertEqual(len(alerts), 1)
        self.assertIn(
            "剩余未修复条数=6", f"{alerts[0].get('description')} {alerts[0].get('evidence')}",
            "读台账失败 MUST 回退进度 total-done",
        )
        self.assertIn("剩余未修复条数：6", _todo_text(proot))
        self.assertFalse(read_progress(proot)["running"])


if __name__ == "__main__":
    unittest.main()

"""verifier 重验车道派发闸门回归（orphaned_state 驱动链路修复）。

事故形态（2026-09-17 fix-robustness-edge-cases 孤儿信号）：
spec 在 testing 态无驱动，框架三条恢复车道
（`event_bus._recover_testing`、`admin_monitor._reset_orphaned_after_disposition`、
`admin_monitor._reset_env_blocked_after_disposition`）都按「重验」语义
`handle_event("spec_implemented") → _on_spec_implemented → _enqueue(spec, "verifier")`，
但 `Dispatcher._process_queue` 的 verifier 状态守卫是 `status != "implemented"`
→ 已在 testing 的 spec 入队的 verifier 条目**永不派发**，静默滞留在队列
（实测：04:12 的孤儿信号即由此产生；历史 20:15/20:45 多次
「Recovery: re-triggering verify for undriven testing」均只有 Queued 无 Dispatching）。
车道空转的直接后果：testing 无驱动只能等 260 分钟 stuck 阈值兜底回 implemented。

本测试钉住：testing 态 verifier 可派发（重验车道出口成立），
其余状态（verified/ready 等）仍被守卫拦住，正常 implemented→verifier 路径不变。
"""

import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine
from core.state_machine import StateMachine


def _make_engine(tmpdir: Path, status: str):
    """构造 PMEngine，spec 处于指定状态，stub 掉真实 worker 启动。"""
    (tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = MagicMock()
    sm = StateMachine(tmpdir / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), {}, tmpdir, logger)
    dispatched: list = []
    engine._run_agent_worker = lambda spec, atype, prio: dispatched.append((spec, atype))
    sm.add_spec("demo", {"status": status, "priority": 5})
    return sm, engine, dispatched


def _drain_queue(engine: PMEngine):
    """触发派发并给 worker 线程（已 stub，仅记录）留出执行窗口。"""
    engine._dispatcher._process_queue()
    time.sleep(0.3)


class TestVerifierDispatchReverifyLane:
    def test_testing_spec_dispatches_queued_verifier(self, tmp_path):
        """testing 态入队的 verifier MUST 被派发（重验车道出口）。

        回归事故本体：三条恢复车道都在 testing 态入队 verifier，
        守卫 `status != "implemented"` 让条目永久滞留队列。
        """
        sm, engine, dispatched = _make_engine(tmp_path, "testing")
        engine._dispatcher._enqueue("demo", "verifier")
        _drain_queue(engine)

        assert dispatched == [("demo", "verifier")], "testing 态 verifier 未被派发（车道空转）"
        assert engine._dispatcher._run_queue == [], "已派发的条目不得滞留队列"
        # 幂等自迁移：dispatch 前的 transition(testing) 不改变状态
        assert sm.read_one("demo")["status"] == "testing"

    def test_implemented_spec_still_dispatches_verifier(self, tmp_path):
        """正常路径回归：implemented 态 verifier 照常派发。"""
        sm, engine, dispatched = _make_engine(tmp_path, "implemented")
        engine._dispatcher._enqueue("demo", "verifier")
        _drain_queue(engine)

        assert dispatched == [("demo", "verifier")]

    @pytest.mark.parametrize("status", ["verified", "ready", "drafting-blank", "pushed"])
    def test_invalid_states_do_not_dispatch_verifier(self, tmp_path, status):
        """守卫不放宽：非 implemented/testing 态入队的 verifier 不得派发。"""
        sm, engine, dispatched = _make_engine(tmp_path, status)
        engine._dispatcher._enqueue("demo", "verifier")
        _drain_queue(engine)

        assert dispatched == [], f"{status} 态不应派发 verifier"
        # 条目保持滞留（由既有清理路径处理），关键是不被误派发
        assert engine._dispatcher._run_queue != []

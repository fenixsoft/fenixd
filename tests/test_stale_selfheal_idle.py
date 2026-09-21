"""fix-state-atomicity-and-selfheal-restart 4.2 — 自愈空闲判定（评审车道）契约测试。

对应 spec/changes/fix-state-atomicity-and-selfheal-restart/specs/stale-code-selfheal/spec.md
的 MODIFIED Requirement「空闲判定语义」与「空闲感知的陈旧自愈触发」：

- Scenario 评审 run 在飞时判定为非空闲（评审车道在飞独立构成非空闲）
- Scenario 停滞的评审 run 不因转录不增长而判空闲（进程表判据为真相）
- Scenario 陈旧锚点不永久占据非空闲（死亡/收口 run 不阻碍自愈触发）
- Scenario 停滞中的在飞 run 视为非空闲（restart_request MUST NOT 被写入）

**回归锚点**：`test_stalled_review_run_is_not_idle` /
`test_stalled_review_run_blocks_selfheal_tick` 在未修补实现上必然失败——修补前
`_is_idle()` 只读 `_active_runs`（评审 run 从不计入它，恒为 0）与 admin 池，
故「评审 run 停滞在飞」会被判空闲、连续 120s 后 touch restart_request 杀掉在跑
run（2026-09-21 事故）。

判定链路复用**真实实现**：`PMEngine.review_anchors` / `PMEngine.is_review_in_flight`
（只读门面）与 `LivenessSupervisor.reviewer_in_flight`（分层判据，进程表为真相）。
只有 StateMachine 的锚点落点、AgentRunner 的进程注册表（`running_run_ids`）与
run 流文件是测试夹具。
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# 模块级 import：pytest 执行期 sys.path 变化可能撞仓库根同名包
import fenixd as _fenixd_mod  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.fenix_session as fenix_session  # noqa: E402
from core.admin_store import AdminStore  # noqa: E402
from core.agent_runner.liveness import LivenessSupervisor  # noqa: E402
from core.pm_engine.engine import PMEngine  # noqa: E402
from core.state_machine import StateMachine  # noqa: E402

SPEC = "demo"
REVIEW_RUN = "spec-review-demo-1789964873"


class _FakeRunnerFacade:
    """AgentRunner 瘦门面：只提供 `LivenessSupervisor` 分层判据所需的进程注册表。

    `running_run_ids()` 即 daemon 进程内 run 注册表（判据 2）。停滞评审 run 的
    转录不增长、流文件陈旧，只有该判据能把它认成「在飞」——这正是本 SPEC 要求
    的「以进程存活为主判据」。
    """

    def __init__(self, project_root, running_ids=(), pm_engine_ref=None):
        self.project_root = Path(project_root)
        self.logger = mock.MagicMock()
        self._running = list(running_ids)
        self._pm_engine_ref = pm_engine_ref

    def running_run_ids(self):
        return list(self._running)


class _Harness:
    """最小项目 + 裸 daemon：StateMachine 真身、pm_engine 只读门面真身。"""

    def __init__(self, tmpdir, *, reviewer_run=REVIEW_RUN, running_ids=(),
                 active_reviews=()):
        self.proot = Path(tmpdir)
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)
        self.sm = StateMachine(self.proot / ".fenix" / "STATE.md", mock.MagicMock())
        self.sm.add_spec(
            SPEC,
            {
                "status": "reviewing",
                "priority": 5,
                "branch": None,
                "error": None,
                "reviewer_run": reviewer_run,
            },
        )
        # pm_engine 替身：仅承载 PMEngine 只读门面的两个真实实现
        self.pm = SimpleNamespace(
            _active_runs=0,
            state_machine=self.sm,
            logger=mock.MagicMock(),
            _queue_lock=threading.Lock(),
            _active_reviews=set(active_reviews),
        )
        self.pm.review_anchors = lambda: PMEngine.review_anchors(self.pm)
        self.pm.has_queued_review = lambda: PMEngine.has_queued_review(self.pm)
        self.pm.is_review_in_flight = lambda name: PMEngine.is_review_in_flight(
            self.pm, name
        )
        self.runner = _FakeRunnerFacade(
            self.proot, running_ids, pm_engine_ref=self.pm
        )
        self.pm.agent_runner = LivenessSupervisor(self.runner)
        self.daemon = self._build_daemon()
        self.req = self.proot / ".fenix" / "restart_request"

    def _build_daemon(self):
        daemon = _fenixd_mod.FenixDaemon.__new__(_fenixd_mod.FenixDaemon)
        daemon.config = {}
        daemon.logger = mock.MagicMock()
        daemon.admin_store = AdminStore(self.proot, daemon.logger)
        daemon.pm_engine = self.pm
        daemon._admin_executor = None
        daemon._admin_pool_lock = threading.Lock()
        daemon._admin_pool_stats = {"submitted": 0, "completed": 0, "failed": 0}
        daemon._code_stale = True
        daemon._stale_idle_since = None
        daemon._heal_block_reason = None
        return daemon

    # ── 夹具 ────────────────────────────────────────────────

    def write_stream(self, run_id=REVIEW_RUN, tail="system", age_seconds=3600):
        """写 run 流文件并把 mtime 拨到 age_seconds 前（模拟转录停止增长）。

        tail 取值见 RUN_TERMINAL_EVENT_TYPES：result/interrupted/error/cancelled
        为终态，system/tool_use 等为非终态（在跑）。
        """
        p = self.proot / ".fenix" / "runs" / f"{run_id}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"type": "init", "timestamp": "2026-01-01T00:00:00Z"})
            + "\n"
            + json.dumps({"type": tail, "timestamp": "2026-01-01T00:00:01Z"})
            + "\n",
            encoding="utf-8",
        )
        t = time.time() - age_seconds
        os.utime(p, (t, t))
        return p

    def tick(self):
        self.daemon._maybe_stale_selfheal_tick()

    def tick_near_threshold(self, seconds=300):
        """把「已连续空闲」拨到阈值之上后 tick 一次（触发窗口内）。"""
        self.daemon._stale_idle_since = time.time() - seconds
        self.tick()


class _IdleBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._mp_root = mock.patch.object(
            _fenixd_mod, "PROJECT_ROOT", Path(self.tmpdir)
        )
        self._mp_root.start()
        self._sup = mock.patch.object(
            fenix_session, "supervisor_running", return_value=True
        )
        self._sup.start()

    def tearDown(self):
        self._sup.stop()
        self._mp_root.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def harness(self, **kwargs):
        return _Harness(self.tmpdir, **kwargs)


class TestReviewerLaneIdle(_IdleBase):
    def test_no_review_anchor_is_idle(self):
        """基线：无 reviewer_run 锚点 → 评审维度不占位，判定为空闲。"""
        h = self.harness(reviewer_run=None)
        assert h.daemon._is_idle() is True
        assert h.pm.review_anchors() == {}

    def test_stalled_review_run_is_not_idle(self):
        """4.2①：评审 run 在飞且转录停滞 → 非空闲。

        构造口径与事故逐条对齐：`_active_runs == 0`（评审 run 从不计入）、
        `reviewer_run` 锚点非空、run 在 `running_run_ids()` 中、流文件停止增长
        （mtime 1 小时前 + 末行非终态）。
        """
        h = self.harness(running_ids=[REVIEW_RUN])
        h.write_stream(tail="system", age_seconds=3600)
        assert h.pm._active_runs == 0, "评审 run 不应计入实现车道"
        in_flight, reason = h.pm.agent_runner.reviewer_in_flight(SPEC, REVIEW_RUN)
        assert (in_flight, reason) == (True, "process"), (
            "在飞依据必须是进程表（停滞 run 转录本就不增长），"
            f"实际 {(in_flight, reason)}"
        )
        assert h.daemon._is_idle() is False, (
            "评审车道在飞必须独立构成非空闲（修补前 _active_runs==0 即判空闲）"
        )

    def test_stalled_review_run_blocks_selfheal_tick(self):
        """4.2①：停滞评审 run 存在时自愈 MUST NOT 写入 restart_request。"""
        h = self.harness(running_ids=[REVIEW_RUN])
        h.write_stream(tail="system", age_seconds=3600)
        h.tick_near_threshold(300)
        assert not h.req.exists(), "自愈打断了在飞评审 run"
        assert h.daemon._stale_idle_since is None, "非空闲出现必须立即清零连续空闲计时"
        for _ in range(3):
            h.tick_near_threshold(300)
        assert not h.req.exists()

    def test_dead_review_anchor_does_not_block_idle(self):
        """4.2②：死亡/收口 run（进程表无、末行终态）判 stale，不阻碍自愈触发。"""
        h = self.harness(running_ids=())
        h.write_stream(tail="result", age_seconds=3600)
        in_flight, reason = h.pm.agent_runner.reviewer_in_flight(SPEC, REVIEW_RUN)
        assert (in_flight, reason) == (False, "stale")
        assert h.daemon._is_idle() is True, "陈旧锚点 MUST NOT 永久占据非空闲"
        h.tick_near_threshold(300)
        assert h.req.exists(), "真正空闲时自愈必须仍可触发"

    def test_anchor_in_flight_after_active_reviews_released(self):
        """4.2③：`_active_reviews` 已释放但锚点仍在飞的窗口内仍判非空闲。

        防「只加 `_active_reviews` 一维」的退化实现——该登记的释放时点早于
        dispatch_review，锚点落盘后即消失，覆盖不了评审 run 的其余生命周期。
        """
        h = self.harness(running_ids=[REVIEW_RUN], active_reviews=())
        h.write_stream(tail="system", age_seconds=3600)
        assert h.pm.is_review_in_flight(SPEC) is False, "前置：队列登记已释放"
        assert h.daemon._is_idle() is False, "锚点仍在飞必须仍判非空闲"
        h.tick_near_threshold(300)
        assert not h.req.exists()

    def test_queued_review_without_anchor_is_not_idle(self):
        """评审条目已入队、锚点尚未落盘的窗口：经 `_active_reviews` 判非空闲。"""
        h = self.harness(reviewer_run=None, active_reviews=[SPEC])
        assert h.pm.review_anchors() == {}, "前置：锚点尚未落盘"
        assert h.pm.is_review_in_flight(SPEC) is True
        assert h.daemon._is_idle() is False

    def test_fresh_stream_without_process_keeps_not_idle(self):
        """判据 3 兜底：进程表未登记但流文件新鲜且末行非终态 → 仍判在飞。"""
        h = self.harness(running_ids=())
        h.write_stream(tail="tool_use", age_seconds=1)
        in_flight, reason = h.pm.agent_runner.reviewer_in_flight(SPEC, REVIEW_RUN)
        assert (in_flight, reason) == (True, "stream")
        assert h.daemon._is_idle() is False


class TestReviewAnchorFacade(_IdleBase):
    def test_review_anchors_narrows_candidates(self):
        """只读门面：仅枚举 `reviewer_run` 非空的条目。"""
        h = self.harness(running_ids=[])
        h.sm.add_spec("plain", {"status": "ready", "reviewer_run": None})
        anchors = h.pm.review_anchors()
        assert anchors == {SPEC: REVIEW_RUN}

    def test_review_anchors_survives_unreadable_state(self):
        """STATE 不可读 → 空候选（调用方另有保守兜底），不抛异常。"""
        h = self.harness()
        h.pm.state_machine = SimpleNamespace(
            read_all=mock.MagicMock(side_effect=OSError("boom"))
        )
        assert h.pm.review_anchors() == {}


if __name__ == "__main__":
    unittest.main()

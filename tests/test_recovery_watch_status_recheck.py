"""
tests/test_recovery_watch_status_recheck.py — evo-recovery-watch-status-recheck 测试。

升级前状态/运行痕迹复查与有界顺延：框架内重试在途（transient_retry/superseded
末事件）不误报、归档形态仍检、blocked 关闭不重复告警、无正向证据仍升级、
顺延有界性（defer_limit_minutes）与保守失败（重读异常仍升级）。
"""

import json
import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.pm_engine import PMEngine
from core.state_machine import StateMachine
from core.admin_store import AdminStore
from core.pm_engine.recovery import (
    DEFAULT_DEFER_LIMIT_MINUTES,
    DEFAULT_INFLIGHT_RETRY_MINUTES,
)

NS_PER_MIN = 60.0  # 分钟 → 秒


class RecoveryWatchStatusRecheckFixture(unittest.TestCase):
    """夹具：真实 StateMachine + MagicMock worktree_manager（与既有夹具同源）"""

    def setUp(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger)
        self.runner = MagicMock()
        self.runner.worktree_manager = MagicMock()
        # 显式关闭活跃派发：MagicMock.has_active_worktree 默认返回 MagicMock
        # （bool 为 True），会误判 spec 有活跃派发而跳过 stale 判定。
        self.runner.worktree_manager.has_active_worktree.return_value = False
        self.engine = PMEngine(
            self.sm, self.runner, {},
            self.project_root, self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 辅助方法 ─────────────────────────────────────────────────────

    def _create_spec(self, name="s1", status="ready"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, status)
        return self.sm.read_one(name)

    def _watch_due(self, name="s1"):
        """把观察项 due 推前到已过期"""
        self.engine._recovery._recovery_watch[name]["due"] = time.time() - 1
        self.engine._recovery._save_recovery_watch()

    def _write_retry_stream(self, name, event_types, ts_minutes_ago,
                            mtime_minutes_ago=None, in_archive=False):
        """写归属该 spec 的 impl 流，末事件为 event_types 的最后一个。

        ts_minutes_ago：末事件 timestamp 距 now 的分钟数（重试窗口判据用）；
        mtime_minutes_ago（缺省同 ts）：文件 mtime 距 now 的分钟数——置旧以
        避开 D2(a) 60s succeed 缓冲（重试窗口测试必须与过渡窗口隔离）。
        """
        runs_dir = self.project_root / ".fenix" / "runs"
        target = runs_dir / "archive" if in_archive else runs_dir
        target.mkdir(parents=True, exist_ok=True)
        stream = target / f"impl-{name}-1789999999.jsonl"
        ts = (datetime.now(timezone.utc) -
              timedelta(minutes=ts_minutes_ago)).isoformat()
        lines = ['{"type":"start"}\n']
        for etype in event_types:
            lines.append(
                json.dumps({
                    "type": etype, "spec": name,
                    "provider": "test", "timestamp": ts,
                }) + "\n"
            )
        stream.write_text("".join(lines), encoding="utf-8")
        if mtime_minutes_ago is None:
            mtime_minutes_ago = ts_minutes_ago
        target_ts = time.time() - mtime_minutes_ago * NS_PER_MIN
        os.utime(stream, (target_ts, target_ts))
        return stream


class TestInflightRetryDefer(RecoveryWatchStatusRecheckFixture):
    """2.1：框架内重试在途（末事件 transient_retry/superseded 未超窗口）→ 顺延不升级。

    复现 2026-09-17 16:33:58Z 误报：16:30:31Z artifact-gate 不一致触发
    in-place retry（transient_retry + superseded），16:34:55Z 重试 run 才开始
    输出——间隙内 spec 无活跃派发、流 mtime 不新鲜，但重试在途证据存在 → 顺延。
    """

    def _setup_implementing_inflight(self, event_types):
        self._create_spec("s1", "implementing")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        # 末事件 2 分钟前（在 inflight_retry_minutes=5 窗口内）；mtime 同样置
        # 旧（90s 外）避开 D2(a) 60s 缓冲，隔离证明是重试在途判据顺延。
        self._write_retry_stream("s1", event_types, ts_minutes_ago=2,
                                 mtime_minutes_ago=2)

    def test_superseded_last_event_defers(self):
        """末事件 superseded（runner 终态补写）→ 顺延不升级"""
        self._setup_implementing_inflight(["transient_retry", "superseded"])
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        # 观察项保留且 due 已推进
        self.assertIn("s1", self.engine._recovery._recovery_watch)
        self.assertGreater(
            self.engine._recovery._recovery_watch["s1"]["due"], time.time())

    def test_transient_retry_last_event_defers(self):
        """末事件 transient_retry（同属重试留痕类型）→ 顺延不升级"""
        self._setup_implementing_inflight(["transient_retry"])
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        self.assertIn("s1", self.engine._recovery._recovery_watch)

    def test_defer_persisted_to_json(self):
        """顺延后观察项持久化在 .fenix/recovery_watch.json（防裸 continue 丢弃）"""
        self._setup_implementing_inflight(["transient_retry", "superseded"])
        self.engine.check_recovery_watch()
        watch_path = self.project_root / ".fenix" / "recovery_watch.json"
        data = json.loads(watch_path.read_text(encoding="utf-8"))
        self.assertIn("s1", data)
        self.assertGreater(data["s1"]["due"], time.time())

    def test_retry_evidence_survives_archive_only(self):
        """2.2：痕迹仅在 .fenix/runs/archive/（顶层无副本）→ 仍顺延"""
        self._create_spec("s1", "implementing")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        # 终态流已被保留清理归档：只有 archive/ 副本，顶层无同名流
        self._write_retry_stream("s1", ["transient_retry", "superseded"],
                                 ts_minutes_ago=2, mtime_minutes_ago=2,
                                 in_archive=True)
        self.assertFalse(
            (self.project_root / ".fenix" / "runs" /
             "impl-s1-1789999999.jsonl").exists())
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        self.assertIn("s1", self.engine._recovery._recovery_watch)

    def test_archive_prefix_guard(self):
        """归档检索也做前缀歧义守卫：他 spec 前缀命中不算归属本 spec 的证据"""
        self._create_spec("s1", "implementing")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        # archive 里只有 impl-a-b-c 流（spec a-b 的前缀含 a 的情形：a-a-b 等）——
        # 归属 spec "a-b" 的流应为 impl-a-b-*，impl-a-b-c-* 是 spec "a-b-c" 的。
        self._write_retry_stream("a-b-c", ["superseded"], ts_minutes_ago=2,
                                 mtime_minutes_ago=2, in_archive=True)
        # spec s1 无任何归属痕迹 → 无正向证据 → 仍升级
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)


class TestInflightRetryWindowTimeout(RecoveryWatchStatusRecheckFixture):
    """2.3：重试窗口超时（末事件距 now > inflight_retry_minutes）→ 仍升级"""

    def test_event_older_than_window_upgrades(self):
        self._create_spec("s1", "implementing")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        # 末事件 6 分钟前 > 缺省 5 分钟窗口；mtime 同样超缓冲
        self._write_retry_stream("s1", ["transient_retry", "superseded"],
                                 ts_minutes_ago=6, mtime_minutes_ago=6)
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)
        recs = AdminStore(self.project_root, self.logger).read_all()
        stalled = [r for r in recs if r.get("signal_type") == "dispatch_stalled"]
        self.assertEqual(len(stalled), 1)


class TestBlockedDelegatedToBlockedStuck(RecoveryWatchStatusRecheckFixture):
    """2.4：复查时已 blocked（含 frozen）→ 关闭观察项、不升级、无信号记录。

    blocked 由 admin_monitor._detect_blocked_stuck 独立通道告警
    （core/admin_monitor.py:690），recovery watch 再升级属重复告警
    （2026-09-17 事故 16:37Z 双通道并存同一 spec）。
    """

    def test_blocked_closes_watch_no_alert(self):
        self._create_spec("s1", "ready")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        self.sm.update_spec("s1", {"status": "blocked"})
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        # 观察项已关闭（不再挂起复查）
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(
            [r for r in recs if r.get("signal_type") == "dispatch_stalled"], [])

    def test_frozen_blocked_closes_watch_no_alert(self):
        """frozen blocked（结构化 frozen 标记）同样关闭不告警"""
        self._create_spec("s1", "ready")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        self.sm.update_spec(
            "s1", {"status": "blocked", "frozen": True,
                   "error": "frozen by user instruction"})
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(
            [r for r in recs if r.get("signal_type") == "dispatch_stalled"], [])


class TestNoEvidenceStillUpgrades(RecoveryWatchStatusRecheckFixture):
    """2.5/2.6：无正向证据的停滞态仍升级（不因 status 非 ready 豁免）"""

    def test_implementing_no_evidence_upgrades(self):
        """2.5：implementing + 无活跃派发 + 无运行痕迹 → 仍升级

        对齐 test_defer_registers_watch_no_deadloop 的「到期即信号」不变量
        （recovery.py:35-39 刻意设计：无活跃派发的 implementing 属卡死形态）。
        """
        self._create_spec("s1", "implementing")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(len(
            [r for r in recs if r.get("signal_type") == "dispatch_stalled"]), 1)

    def test_ready_stuck_upgrades(self):
        """2.6：确为 ready 滞留（就地重派被闸门拦下）→ 仍升级（回归 3fad3350）

        内容完整性闸门在就地重派路径上把 ready 冻结为 blocked——该形态属
        「重派未成立」既有升级路径，blocked 豁免只作用于复查时已 blocked
        （第 2 层首次 read_one），不吞掉本路径升级。
        """
        self._create_spec("s1", "ready")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)
        recs = AdminStore(self.project_root, self.logger).read_all()
        stalled = [r for r in recs if r.get("signal_type") == "dispatch_stalled"]
        self.assertEqual(len(stalled), 1)


class TestDeferBoundedness(RecoveryWatchStatusRecheckFixture):
    """2.7：顺延有界性——累计顺延超过 defer_limit_minutes → 回落升级"""

    def _setup_watch_with_deadline(self, deadline_ago_minutes):
        self._create_spec("s1", "implementing")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        # recheck_deadline（首个 due 到期时刻）回拨到 deadline_ago_minutes 前
        self.engine._recovery._recovery_watch["s1"]["recheck_deadline"] = \
            time.time() - deadline_ago_minutes * NS_PER_MIN
        self.engine._recovery._save_recovery_watch()

    def test_defer_limit_exceeded_falls_back(self):
        """重试在途仍命中，但自 recheck_deadline 起累计顺延已超 30min → 升级"""
        self._setup_watch_with_deadline(
            DEFAULT_DEFER_LIMIT_MINUTES + 1)
        self._write_retry_stream("s1", ["superseded"], ts_minutes_ago=2,
                                 mtime_minutes_ago=2)
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])
        self.assertNotIn("s1", self.engine._recovery._recovery_watch)
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(len(
            [r for r in recs if r.get("signal_type") == "dispatch_stalled"]), 1)

    def test_transition_window_also_bounded_by_limit(self):
        """D2(a) 过渡窗口同样受 defer_limit 门：超限后窗口内也不顺延"""
        self._setup_watch_with_deadline(
            DEFAULT_DEFER_LIMIT_MINUTES + 1)
        # 流 mtime 30s 前（D2(a) 60s 缓冲本应命中）
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(exist_ok=True)
        stream = runs_dir / "impl-s1-1789999999.jsonl"
        stream.write_text('{"type":"start"}\n', encoding="utf-8")
        target_ts = time.time() - 30
        os.utime(stream, (target_ts, target_ts))
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])

    def test_defer_within_limit_still_defers(self):
        """未超限时重试在途照常顺延（有界性不误伤窗口内豁免）"""
        self._create_spec("s1", "implementing")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        # recheck_deadline 在 10 分钟前（< 30min 上限，且 > followup 15min 保证
        # 观察项已到期）——仍可顺延
        self.engine._recovery._recovery_watch["s1"]["recheck_deadline"] = \
            time.time() - 10 * NS_PER_MIN
        self.engine._recovery._save_recovery_watch()
        self._write_retry_stream("s1", ["superseded"], ts_minutes_ago=2,
                                 mtime_minutes_ago=2)
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, [])
        self.assertIn("s1", self.engine._recovery._recovery_watch)


class TestConservativeFailure(RecoveryWatchStatusRecheckFixture):
    """2.8：升级前重读状态/运行痕迹抛异常 → 保守升级"""

    def test_state_repeat_read_failure_conservatively_upgrades(self):
        """第 3 层升级前重读 read_one 抛异常 → 保守升级（不静默关闭）"""
        self._create_spec("s1", "ready")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        # 就地重派被预算闸门拦下（不改状态），随后升级前重读抛异常
        self.engine._check_impl_budget_exhausted = MagicMock(return_value=True)
        orig_read = self.sm.read_one
        state = {"n": 0}

        def flaky(name, *args, **kwargs):
            state["n"] += 1
            if state["n"] == 3:  # 第 3 次 = 升级前重读（180 行 1 次 + 冻结探针 1 次）
                raise RuntimeError("state read failed before escalation")
            return orig_read(name, *args, **kwargs)

        self.sm.read_one = flaky
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])
        recs = AdminStore(self.project_root, self.logger).read_all()
        self.assertEqual(len(
            [r for r in recs if r.get("signal_type") == "dispatch_stalled"]), 1)

    def test_unreadable_retry_stream_conservatively_upgrades(self):
        """运行痕迹读取异常（流损坏不可解析）→ 保守不豁免 → 仍升级

        流末事件解析失败按无正向证据处理（宁可多报 stale，不把真实卡死洗成
        健康）——与 design「重读失败保守升级」同向。
        """
        self._create_spec("s1", "implementing")
        self.engine.register_recovery_watch("s1", "test")
        self._watch_due("s1")
        # 归属该 spec 的流存在但末行非法 JSON
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        stream = runs_dir / "impl-s1-1789999999.jsonl"
        stream.write_text('{"type":"start"}\nINVALID-JSON\n', encoding="utf-8")
        target_ts = time.time() - 2 * NS_PER_MIN
        os.utime(stream, (target_ts, target_ts))
        raised = self.engine.check_recovery_watch()
        self.assertEqual(raised, ["s1"])


if __name__ == "__main__":
    unittest.main()
"""双派发防御与人工冻结语义测试（fix-restart-dual-dispatch）。

背景（2026-09-03 事故）：daemon 重启恢复时两条恢复路径同秒对同一 spec 双派
implementer——stale 锁误释放 + create 入口 check-then-add TOCTOU + 同秒同名
分支 fatal + attempt 换名重试成功，最终两个 claude 并行跑同一 spec。人工冻结
的 admin 豁免此前依赖 error 文本匹配（frozen:/用户指令），文案漂移即失效
（实测「人工冻结（…）」绕过豁免，admin 每 15 分钟空探一次烧 token）。

覆盖：
- S2 派发幂等：create 锁 check-then-add 原子化（并发只有一个胜出、持锁者
  锁不被他人失败路径误删）、has_active_lock 判定
- S3 失败快停：attempt 重试前锁活跃/人工冻结 → 放弃重试
  （_should_give_up_before_retry）
- S4 冻结语义：StateMachine 层剥离 frozen spec 的 status 更新（82 个调用点
  一次性收口）、freeze/unfreeze helper、blocked_stuck 对 frozen 零信号、
  Administrator 唤起前复查
"""

import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.state_machine import StateMachine
from core.worktree_manager import WorktreeManager
from core.agent_runner.runner import AgentRunner
from core.admin_monitor import AdminMonitor


class CapturingLogger:
    """记录 warning/info 文本，供断言使用。"""

    def __init__(self):
        self.warnings = []
        self.infos = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.infos.append(msg)

    def warning(self, *a, **k):
        msg = a[1] if len(a) > 1 else (a[0] if a else "")
        if isinstance(msg, str):
            self.warnings.append(msg)

    def error(self, *a, **k):
        pass


def init_repo(root: Path):
    import subprocess

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True, check=True)

    root.mkdir(parents=True, exist_ok=True)
    git("init", "-q")
    git("config", "user.email", "test@fenix.local")
    git("config", "user.name", "Fenix Test")
    git("config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "[fenix] base")
    git("branch", "-M", "main")


class TestWorktreeLockIdempotency(unittest.TestCase):
    """S2：create 锁原子性——并发派发同一 spec 只有一个胜出。"""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="fenix-lock-test-"))
        self.repo = self.tmp / "repo"
        init_repo(self.repo)
        self.logger = CapturingLogger()
        self.wm = WorktreeManager(
            base_dir=self.tmp / "worktrees",
            project_root=self.repo,
            logger=self.logger,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_concurrent_create_only_one_wins(self):
        """8 线程并发 create 同 spec：恰有一个成功，其余 None。"""
        def create(_):
            return self.wm.create("spec-x", "implementer")

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(create, range(8)))

        ok = [r for r in results if r is not None]
        self.assertEqual(len(ok), 1,
                         f"并发 create 应恰好一个胜出，实际 {len(ok)}: {results}")
        # 胜出者锁保持（由 cleanup 释放），工作区在册
        self.assertTrue(self.wm.has_active_lock("spec-x", "implementer"))
        self.assertIn(str(ok[0]), self.wm._active_worktrees)

    def test_create_blocked_by_active_lock(self):
        """持锁期间 create 返回 None，锁不被误删。"""
        self.wm._spec_locks.add("spec-y:implementer")
        result = self.wm.create("spec-y", "implementer")
        self.assertIsNone(result)
        self.assertTrue(self.wm.has_active_lock("spec-y", "implementer"),
                        "被拦方的失败不得误删持锁者的锁")
        self.assertIn("Worktree already active", " ".join(self.logger.warnings))

    def test_failed_create_releases_own_lock(self):
        """git 层失败（分支已存在）：返回 None、释放自己的锁、重试可用。"""
        # 冻结时间戳，预建同名分支制造 fatal
        frozen_ts = 1700000000
        import subprocess
        subprocess.run(
            ["git", "-C", str(self.repo), "branch",
             f"fenix/spec-z-{frozen_ts}"],
            check=True, capture_output=True,
        )
        with patch("core.worktree_manager.time.time", return_value=frozen_ts):
            result = self.wm.create("spec-z", "implementer")

        self.assertIsNone(result)
        self.assertFalse(self.wm.has_active_lock("spec-z", "implementer"),
                         "失败方必须释放自己 acquire 的锁，否则重试永远被拦")

        # 释放后立即重试（新时间戳）应成功——单发场景的瞬时故障恢复语义保留
        result2 = self.wm.create("spec-z", "implementer")
        self.assertIsNotNone(result2)
        self.assertTrue(self.wm.has_active_lock("spec-z", "implementer"))

    def test_has_active_lock(self):
        self.assertFalse(self.wm.has_active_lock("spec-a", "implementer"))
        self.wm._spec_locks.add("spec-a:implementer")
        self.assertTrue(self.wm.has_active_lock("spec-a", "implementer"))
        self.assertFalse(self.wm.has_active_lock("spec-a", "verifier"))


class TestRetryGiveUp(unittest.TestCase):
    """S3：attempt 重试前的放弃判定——锁活跃或人工冻结时不再重试。"""

    def _make_runner(self):
        runner = AgentRunner.__new__(AgentRunner)
        runner.worktree_manager = MagicMock()
        runner.state_machine = MagicMock()
        runner.logger = CapturingLogger()
        return runner

    def test_give_up_when_lock_active(self):
        """另一 run 持锁（并行风险）→ 放弃重试。"""
        runner = self._make_runner()
        runner.worktree_manager.has_active_lock.return_value = True
        runner.state_machine.read_one.return_value = {}
        self.assertTrue(
            runner._should_give_up_before_retry("spec-a", "implementer"))

    def test_give_up_when_frozen(self):
        """spec 被人工冻结 → 放弃重试。"""
        runner = self._make_runner()
        runner.worktree_manager.has_active_lock.return_value = False
        runner.state_machine.read_one.return_value = {"frozen": True}
        self.assertTrue(
            runner._should_give_up_before_retry("spec-a", "implementer"))

    def test_no_give_up_normal_case(self):
        """锁空闲 + 未冻结 → 正常重试。"""
        runner = self._make_runner()
        runner.worktree_manager.has_active_lock.return_value = False
        runner.state_machine.read_one.return_value = {"status": "implementing"}
        self.assertFalse(
            runner._should_give_up_before_retry("spec-a", "implementer"))

    def test_check_failure_fails_open(self):
        """检查自身异常时不阻塞重试主路径（fail-open）。"""
        runner = self._make_runner()
        runner.worktree_manager.has_active_lock.side_effect = RuntimeError("boom")
        self.assertFalse(
            runner._should_give_up_before_retry("spec-a", "implementer"))


class TestFreezeSemantics(unittest.TestCase):
    """S4：frozen 字段的结构化冻结——StateMachine 层一次性收口。"""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="fenix-freeze-test-"))
        self.logger = CapturingLogger()
        self.sm = StateMachine(self.tmp / "STATE.md", self.logger)
        self.sm.add_spec("spec-f", {"priority": 5})
        self.sm.add_spec("spec-n", {"priority": 5})  # 未冻结对照

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _entry(self, name):
        return self.sm.read_all().get(name, {})

    def test_freeze_spec_helper(self):
        """freeze_spec：blocked + frozen 标记 + 规范 error 前缀。"""
        self.assertTrue(self.sm.freeze_spec("spec-f", "人工处置中"))
        entry = self._entry("spec-f")
        self.assertEqual(entry.get("status"), "blocked")
        self.assertTrue(entry.get("frozen"))
        self.assertTrue(entry.get("error", "").startswith("用户指令冻结："))

    def test_update_strips_status_for_frozen(self):
        """frozen spec 的自动 status 更新被剥离，其余字段照写。"""
        self.sm.freeze_spec("spec-f", "人工处置中")
        self.assertTrue(self.sm.update_spec(
            "spec-f", {"status": "ready", "error": "retry-chain 想重派"}))
        entry = self._entry("spec-f")
        self.assertEqual(entry.get("status"), "blocked",
                         "冻结期自动链路不得改写 status")
        self.assertEqual(entry.get("error"), "retry-chain 想重派",
                         "诊断字段照写，不丢上下文")
        self.assertTrue(entry.get("frozen"))

    def test_unfreeze_via_update_allows_status(self):
        """更新含 frozen 键 = 解冻操作本身，status 更新放行。"""
        self.sm.freeze_spec("spec-f", "人工处置中")
        self.assertTrue(self.sm.update_spec(
            "spec-f", {"frozen": False, "status": "ready"}))
        entry = self._entry("spec-f")
        self.assertEqual(entry.get("status"), "ready")
        self.assertFalse(entry.get("frozen"))

    def test_unfreeze_spec_helper(self):
        self.sm.freeze_spec("spec-f", "人工处置中")
        self.assertTrue(self.sm.unfreeze_spec("spec-f", status="testing"))
        entry = self._entry("spec-f")
        self.assertEqual(entry.get("status"), "testing")
        self.assertFalse(entry.get("frozen"))

    def test_non_frozen_unaffected(self):
        """未冻结 spec 的 update_spec 行为零变化（frozen 显式 False，非真值）。"""
        self.assertTrue(self.sm.update_spec("spec-n", {"status": "ready"}))
        entry = self._entry("spec-n")
        self.assertEqual(entry.get("status"), "ready")
        self.assertFalse(entry.get("frozen"))


class TestBlockedStuckFrozenExemption(unittest.TestCase):
    """S4：admin 巡检对人工冻结 spec 零信号、唤起前复查。"""

    def _make_monitor(self):
        mon = AdminMonitor.__new__(AdminMonitor)
        mon.admin_cfg = {"escalation_cooldown_minutes": 15}
        mon.logger = CapturingLogger()
        mon.state_machine = MagicMock()
        mon.store = MagicMock()
        mon.agent_runner = MagicMock()
        return mon

    def _specs(self, frozen=False, legacy_text=False, stale=True):
        updated = (datetime.now(timezone.utc) - timedelta(hours=1)
                   if stale else datetime.now(timezone.utc))
        updated_str = updated.isoformat()
        specs = {}
        if frozen:
            specs["sp-frozen"] = {
                "status": "blocked", "frozen": True,
                "error": "用户指令冻结：处置中", "updated": updated_str,
            }
        if legacy_text:
            specs["sp-legacy"] = {
                "status": "blocked",
                "error": "用户指令暂停：等人工", "updated": updated_str,
            }
        specs["sp-plain"] = {
            "status": "blocked", "error": "熔断：连续失败",
            "updated": updated_str,
        }
        specs["sp-fresh"] = {
            "status": "blocked", "error": "熔断：连续失败",
            "updated": datetime.now(timezone.utc).isoformat(),
        }
        return specs

    def test_frozen_spec_no_signal(self):
        """frozen spec 即使超阈值也不产生 blocked_stuck 信号。"""
        mon = self._make_monitor()
        signals = mon._detect_blocked_stuck(self._specs(frozen=True),
                                            time.time())
        names = [s["spec"] for s in signals]
        self.assertNotIn("sp-frozen", names,
                         "人工冻结 spec 不得触发 blocked_stuck（每 15 分钟空探的根因）")
        self.assertIn("sp-plain", names, "普通 blocked 超时仍需告警（防回归）")

    def test_legacy_text_exemption_kept(self):
        """历史文本契约（用户指令子串）豁免保留，兼容存量 spec。"""
        mon = self._make_monitor()
        signals = mon._detect_blocked_stuck(self._specs(legacy_text=True),
                                            time.time())
        names = [s["spec"] for s in signals]
        self.assertNotIn("sp-legacy", names)

    def test_fresh_blocked_no_signal(self):
        """阈值内的 blocked 不告警（既有语义防回归）。"""
        mon = self._make_monitor()
        signals = mon._detect_blocked_stuck(self._specs(), time.time())
        names = [s["spec"] for s in signals]
        self.assertNotIn("sp-fresh", names)

    def test_invoke_skips_frozen_spec(self):
        """自动唤起路径复查：frozen spec 不唤起、不落冷却锚点（双保险）。"""
        mon = self._make_monitor()
        mon.state_machine.read_one.return_value = {"frozen": True}
        mon.store.latest_signal.return_value = None
        mon.store.unhandled_for.return_value = None
        signal = {"signal_type": "blocked_stuck", "spec": "sp-frozen",
                  "severity": "critical"}
        mon._handle_signal(signal)
        mon.agent_runner.run_administrator.assert_not_called()
        # 冷却锚点也不落——冻结期内该信号类型保持静默
        for call in mon.store.append.call_args_list:
            self.assertNotEqual(
                call.args[0].get("spec") if call.args else None, "sp-frozen",
                "frozen spec 的信号不得写入 store（含冷却锚点）")

    def test_invoke_normal_spec_proceeds(self):
        """未冻结 spec 照常唤起（防回归）。"""
        mon = self._make_monitor()
        mon.state_machine.read_one.return_value = {"status": "blocked"}
        mon.store.latest_signal.return_value = None
        mon.store.unhandled_for.return_value = None
        disp = MagicMock()
        disp.spec = "sp-plain"
        mon.agent_runner.run_administrator.return_value = disp
        signal = {"signal_type": "blocked_stuck", "spec": "sp-plain",
                  "severity": "major"}
        mon._handle_signal(signal)
        mon.agent_runner.run_administrator.assert_called_once()


if __name__ == "__main__":
    unittest.main()

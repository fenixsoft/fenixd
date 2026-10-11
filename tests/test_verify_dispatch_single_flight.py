"""verify 车道同 spec 单飞 + prepare 并发护栏 + 退避自适应 + 降级分流测试
（evo-add-verify-dispatch-single-flight）。

覆盖 tasks 4.1 全部场景：
- 同 spec 双路入队拒绝＋留痕（spec_implemented 事件 / repair 链尾段
  _enqueue_front / admin 复位直通道三例）＋出队分流兜底拒绝与登记
- 在飞收工后再入队放行（合法重验不被阻塞）
- 并发 prepare 护栏（主机级 fcntl 锁串行化；锁等待超时 fail-visible 附
  持有者 pid；worktree 调用不加锁零开销）
- 锁龄自适应退避（长锁延长预算不 210s 定额耗尽；锁龄超 peer 预计提前
  放弃；锁龄不可知保守回固定序列；配置封顶生效）
- 降级分流（worktree 竞争类先重试新流程一次再降级；非竞争类直接降级；
  锁仍活跃不重试）
"""

import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine
from core.pm_engine import engine as pm_engine_module
from core.verify_contract import (
    PREPARE_LOCK_REL,
    PrepareStep,
    VerifyContract,
    _PrepareHostLock,
    run_prepare_steps,
)

CONTENTION_ERROR = "Worktree create failed (gave up: parallel run or manual freeze)"


class CapturingLogger:
    """记录 warning/info 文本，供断言使用（同 test_worktree_acquire_backoff 惯例）。"""

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


# ── 场景 1：verify 单飞入队守卫（事件 / repair 尾段共用入口）──────────


class SingleFlightEngineHarness(unittest.TestCase):
    """全量 PMEngine 装配（同 test_dispatch_aging 惯例），Thread.start 拦截。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        self.logger = mock.MagicMock()
        self.sm = mock.MagicMock()
        self.sm.read_one.return_value = {"status": "implemented", "priority": 5}
        self.sm.transition = mock.MagicMock(return_value=True)
        self.agent_runner = mock.MagicMock()
        self.config = {"agents": {"max_concurrent": 2}}
        self.engine = PMEngine(
            self.sm, self.agent_runner, self.config, self.project_root, self.logger
        )
        self.engine._check_spec_content_missing = lambda n: False
        self.dispatched = []
        self._orig_thread_start = threading.Thread.start

        def fake_start(thread_self):
            if not thread_self.name.startswith("fenix-"):
                self._orig_thread_start(thread_self)
                return
            _, agent_type, spec_name = thread_self.name.split("-", 2)
            priority = thread_self._args[2]
            self.dispatched.append((priority, spec_name, agent_type))

        threading.Thread.start = fake_start

    def tearDown(self):
        threading.Thread.start = self._orig_thread_start
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def guard_warnings(self):
        return [
            c.args[1] for c in self.engine.logger.warning.call_args_list
            if len(c.args) > 1 and "verify 单飞守卫" in c.args[1]
        ]

    def queue_has(self, spec_name, agent_type="verifier"):
        with self.engine._dispatcher._queue_lock:
            return any(
                e[1] == spec_name and e[2] == agent_type
                for e in self.engine._dispatcher._run_queue
            )


class TestVerifySingleFlightEnqueue(SingleFlightEngineHarness):
    """spec scenario「双路入队被拒」：入队双查「未派发队列∪在飞」。"""

    def test_spec_implemented_event_path_rejected(self):
        """事件路径（_on_spec_implemented → _enqueue）命中在飞即拒绝＋留痕。"""
        self.engine._dispatcher._active_verifies.add("spec-a")
        self.engine._enqueue("spec-a", "verifier")
        self.assertFalse(self.queue_has("spec-a"), "在飞期间重复入队必须被拒绝")
        warns = self.guard_warnings()
        self.assertEqual(len(warns), 1)
        self.assertIn("spec-a", warns[0])

    def test_repair_tail_enqueue_front_path_rejected(self):
        """repair 链尾段入口（_enqueue_front）命中在飞即拒绝＋留痕，不插队。"""
        self.engine._dispatcher._active_verifies.add("spec-a")
        self.engine._enqueue_front("spec-a", "verifier")
        self.assertFalse(self.queue_has("spec-a"))
        self.assertEqual(len(self.guard_warnings()), 1)

    def test_requeue_allowed_after_finish(self):
        """spec scenario「在飞结束后放行」：worker finally 摘除后重入队放行。"""
        self.engine._dispatcher._active_verifies.add("spec-a")
        self.engine._dispatcher._active_verifies.discard("spec-a")  # 收工摘除
        self.engine._enqueue("spec-a", "verifier")
        self.assertTrue(self.queue_has("spec-a"), "合法重验不得被单飞守卫阻塞")
        self.assertEqual(self.guard_warnings(), [])

    def test_queue_dedup_still_applies(self):
        """既有队列去重语义不变：无在飞时重复入队仍折叠为单条目。"""
        self.engine._enqueue("spec-a", "verifier")
        self.engine._enqueue("spec-a", "verifier")
        with self.engine._dispatcher._queue_lock:
            self.assertEqual(len(self.engine._dispatcher._run_queue), 1)


class TestVerifySingleFlightDequeue(SingleFlightEngineHarness):
    """出队分流守卫：锁内「查在飞→命中即拒绝留痕并丢弃条目→未命中即登记」。"""

    def _push_entry(self, spec_name, agent_type="verifier", priority=5):
        entry = (priority, spec_name, agent_type, time.time())
        with self.engine._dispatcher._queue_lock:
            self.engine._dispatcher._run_queue.append(entry)

    def test_dequeue_rejects_duplicate_and_discards(self):
        """入队双查被绕过（竞态窗口/旁路）时出队分流兜底：丢弃＋留痕＋记账退还。"""
        self.engine._dispatcher._active_verifies.add("spec-a")
        self._push_entry("spec-a")
        self.engine._process_queue()
        self.assertEqual(self.dispatched, [], "在飞期间不得派出第二个验证 run")
        with self.engine._dispatcher._queue_lock:
            self.assertEqual(self.engine._dispatcher._run_queue, [], "条目应被丢弃")
        self.assertEqual(self.engine._dispatcher._active_runs, 0, "槽位记账须退还")
        self.assertEqual(len(self.guard_warnings()), 1)

    def test_dequeue_registers_in_flight(self):
        """未命中在飞：正常派发并在出队锁段登记在飞集合。"""
        self._push_entry("spec-a")
        self.engine._process_queue()
        self.assertEqual(
            self.dispatched, [(5, "spec-a", "verifier")], "合法条目应正常派发"
        )
        self.assertIn("spec-a", self.engine._dispatcher._active_verifies)
        self.assertEqual(self.guard_warnings(), [])


class TestAdminResetChannelConvergesToGuard(unittest.TestCase):
    """admin 复位直通道（_reset_env_blocked_after_disposition → handle_event
    ("spec_implemented") → _on_spec_implemented → _enqueue）无旁路，命中在飞
    即被同一守卫拒绝＋留痕。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.logger = CapturingLogger()
        eng = PMEngine.__new__(PMEngine)
        eng.project_root = Path(self.tmpdir)
        eng.logger = self.logger
        eng.state_machine = mock.MagicMock()
        eng.state_machine.read_one.return_value = {"status": "testing", "priority": 5}
        # _enqueue/_enqueue_front 经 _FORWARDER_REGISTRY 委托惰性 _dispatcher
        # 子对象——守卫判据读 dispatcher 的 _active_verifies，须在其上置在飞。
        dispatcher = eng._dispatcher
        dispatcher._active_verifies = {"spec-a"}
        self.engine = eng
        self.dispatcher = dispatcher

        from core.admin_monitor import AdminMonitor

        monitor = AdminMonitor.__new__(AdminMonitor)
        monitor.state_machine = mock.MagicMock()
        monitor.project_root = Path(self.tmpdir)
        monitor.logger = self.logger
        # 在飞互斥守卫（fix-recovery-path-blockers D2）经 _spec_has_active_
        # admin_run 读 store 全库记录；__new__ 裸装配绕过 __init__ 拿不到
        # store——替身给空库（无在飞 admin 处置），守卫放行走直通道。
        monitor.store = mock.MagicMock()
        monitor.store.read_all.return_value = []
        monitor.pm_engine = SimpleNamespace(
            handle_event=lambda kind, spec, entry: (
                self.assertIs(kind, "spec_implemented"),
                eng._on_spec_implemented(spec),
            )[1]
        )
        self.monitor = monitor

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reset_channel_rejected_while_in_flight(self):
        from core import admin_monitor as am

        signal = {"signal_type": "verify_env_blocked", "spec": "spec-a"}
        disp = SimpleNamespace(result="resolved")
        with mock.patch.object(
            am, "resolve_env_blocked_reset_path", return_value="testing"
        ):
            AdminMonitor = am.AdminMonitor
            AdminMonitor._reset_env_blocked_after_disposition(
                self.monitor, signal, disp
            )
        self.assertEqual(
            self.dispatcher._run_queue, [], "admin 直通道重复入队须被单飞守卫拒绝"
        )
        guards = [w for w in self.logger.warnings if "verify 单飞守卫" in w]
        self.assertEqual(len(guards), 1, f"应恰一条拒绝留痕，实得: {guards}")
        self.assertTrue(
            any("复位（直通道）" in i for i in self.logger.infos),
            "复位直通道自身日志应在场（守卫不吞复位动作）",
        )


# ── 场景 2：prepare 并发护栏 ─────────────────────────────────────────


class TestPrepareHostLock(unittest.TestCase):
    """主树 prepare 主机级 fcntl 锁（.fenix/verify-prepare.lock）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _main_root(self):
        root = self.tmp / "main"
        root.mkdir()
        (root / ".git").mkdir()  # 主检出：.git 为目录
        return root

    def test_serialized_by_host_lock(self):
        """前序持有者未释放时 prepare 等待，释放后取得锁并执行（串行化）。"""
        root = self._main_root()
        contract = VerifyContract(prepare=[PrepareStep(run="touch built.txt")])
        holder = _PrepareHostLock(root)
        self.assertTrue(holder.acquire())
        done = []

        def runner():
            done.append(run_prepare_steps(contract, root))

        t = threading.Thread(target=runner)
        t.start()
        time.sleep(0.5)  # 让 runner 进入锁等待
        self.assertEqual(done, [], "持有者未释放前 prepare 不得执行")
        holder.release()
        t.join(timeout=10)
        self.assertEqual(done, [None])
        self.assertTrue((root / "built.txt").exists())

    def test_lock_wait_timeout_fail_visible_with_holder_pid(self):
        """锁等待超时：返回结构化错误（fail-visible），附持有者 pid 供残留诊断。"""
        root = self._main_root()
        contract = VerifyContract(prepare=[PrepareStep(run="touch never-built.txt")])
        holder = _PrepareHostLock(root)
        self.assertTrue(holder.acquire())
        self.addCleanup(holder.release)
        import core.verify_contract as vc

        orig_init = vc._PrepareHostLock.__init__

        def fast_init(lock_self, *a, **k):
            k["timeout"] = 1
            orig_init(lock_self, *a, **k)

        with mock.patch.object(vc._PrepareHostLock, "__init__", fast_init):
            err = run_prepare_steps(contract, root)
        self.assertIsNotNone(err)
        self.assertIn("主机锁等待超时", err)
        self.assertIn(PREPARE_LOCK_REL, err)
        self.assertIn(str(__import__("os").getpid()), err, "应附持有者 pid")
        self.assertFalse((root / "never-built.txt").exists())

    def test_worktree_checkout_skips_lock(self):
        """worktree 调用（.git 为文件）：构建目录 run 级隔离，不加锁零开销。"""
        root = self.tmp / "wt"
        root.mkdir()
        (root / ".git").write_text("gitdir: /somewhere\n", encoding="utf-8")
        contract = VerifyContract(prepare=[PrepareStep(run="touch built.txt")])
        self.assertIsNone(run_prepare_steps(contract, root))
        self.assertTrue((root / "built.txt").exists())
        self.assertFalse(
            (root / ".fenix" / "verify-prepare.lock").exists(), "worktree 不落锁文件"
        )

    def test_step_error_still_surfaces_under_lock(self):
        """护栏不得吞构建错误：主树锁内步骤失败仍按原样返回错误串。"""
        root = self._main_root()
        contract = VerifyContract(prepare=[PrepareStep(run="false")])
        err = run_prepare_steps(contract, root)
        self.assertIsNotNone(err)
        self.assertIn("第 1 步", err)


# ── 场景 3：锁龄自适应退避 ───────────────────────────────────────────


def make_runner(lock_since=None, create_results=None, lock_states=None, config=None):
    """裸装配 runner（同 test_worktree_acquire_backoff 惯例）。"""
    from core.agent_runner.runner import AgentRunner

    runner = AgentRunner.__new__(AgentRunner)
    runner.worktree_manager = mock.MagicMock()
    if lock_since is not None:
        runner.worktree_manager._lock_since = lock_since
    runner.worktree_manager.create.side_effect = list(create_results or [])
    runner.worktree_manager.has_active_lock.side_effect = list(lock_states or [])
    if config is not None:
        runner.config = config
    runner.logger = CapturingLogger()
    runner._log_run_metrics = mock.MagicMock()
    return runner


class TestAdaptiveAcquireBackoff(unittest.TestCase):
    """碰撞退避预算自适应（长锁延长 / 超预期提前放弃 / 锁龄不可知回固定序列）。"""

    def _exhaust(self, runner):
        with mock.patch.object(time, "sleep") as sleeper:
            path, why = runner._create_worktree_with_backoff("spec-a", "verifier")
        waits = [c.args[0] for c in sleeper.call_args_list]
        return path, why, waits

    def test_young_long_lock_extends_budget_beyond_fixed_sequence(self):
        """锁龄 100s（peer 预计 900s）：预算延长至 800s，不再 210s 定额耗尽。"""
        runner = make_runner(
            lock_since={f"spec-a:verifier": time.time() - 100},
            create_results=[None] * 20,
            lock_states=[True] * 20,
        )
        path, why, waits = self._exhaust(runner)
        self.assertIsNone(path)
        self.assertEqual(why, "lock-backoff-exhausted")
        self.assertAlmostEqual(
            sum(waits), 800, delta=1,
            msg=f"自适应预算应恰为 peer 剩余 800s: {waits}",
        )
        self.assertGreater(sum(waits), 210)

    def test_lock_older_than_peer_estimate_gives_up_fast(self):
        """锁龄超 peer 预计时长（僵死/滞留形态）：预算归零快速放弃，零 sleep。"""
        runner = make_runner(
            lock_since={f"spec-a:verifier": time.time() - 1000},
            create_results=[None],
            lock_states=[True],
        )
        path, why, waits = self._exhaust(runner)
        self.assertIsNone(path)
        self.assertEqual(why, "lock-backoff-exhausted")
        self.assertEqual(waits, [], "提前放弃不得空转退避序列")
        self.assertTrue(
            any("early give-up" in w for w in runner.logger.warnings),
            "提前放弃须结构化留痕",
        )

    def test_unknown_lock_age_falls_back_to_fixed_sequence(self):
        """锁龄不可知（桩/缺 _lock_since 登记）：保守回固定 210s 序列（零回退）。"""
        runner = make_runner(create_results=[None] * 4, lock_states=[True] * 4)
        path, why, waits = self._exhaust(runner)
        self.assertIsNone(path)
        self.assertEqual(why, "lock-backoff-exhausted")
        self.assertEqual(waits, [30, 60, 120])

    def test_config_cap_overrides_budget(self):
        """配置封顶生效：预算被 cap 截短，末轮截短后总等待恰为 cap。"""
        runner = make_runner(
            lock_since={f"spec-a:verifier": time.time() - 100},
            create_results=[None] * 8,
            lock_states=[True] * 8,
            config={"worktree": {"acquire_backoff_max_budget_seconds": 100}},
        )
        path, why, waits = self._exhaust(runner)
        self.assertIsNone(path)
        self.assertEqual(why, "lock-backoff-exhausted")
        self.assertEqual(sum(waits), 100)

    def test_acquire_succeeds_within_extended_budget(self):
        """延长预算内 peer 排空：照常取得 worktree（不因自适应而丢取得机会）。"""
        runner = make_runner(
            lock_since={f"spec-a:verifier": time.time() - 100},
            create_results=[None, Path("/tmp/fenix-wt-spec-a")],
            lock_states=[True],
        )
        with mock.patch.object(time, "sleep"):
            path, why = runner._create_worktree_with_backoff("spec-a", "verifier")
        self.assertIsNotNone(path)
        self.assertIsNone(why)


# ── 场景 4：降级分流 ─────────────────────────────────────────────────


class TestVerifierDegradeTriage(unittest.TestCase):
    """worktree 竞争类先重试新流程一次再降级；非竞争类直接降级。"""

    def setUp(self):
        self._orig = pm_engine_module._NEW_VERIFIER_FALLBACK_COUNT
        pm_engine_module._NEW_VERIFIER_FALLBACK_COUNT = 0
        self.addCleanup(setattr, pm_engine_module,
                        "_NEW_VERIFIER_FALLBACK_COUNT", self._orig)

    def _engine(self, lock_active=False, three_stage_side_effect=None):
        eng = PMEngine.__new__(PMEngine)
        eng.config = {}
        eng._get_config = mock.MagicMock(return_value=True)
        eng.logger = CapturingLogger()
        wm = mock.MagicMock()
        wm.has_active_lock = mock.MagicMock(return_value=lock_active)
        eng.agent_runner = SimpleNamespace(worktree_manager=wm)
        eng._run_three_stage_verification = mock.MagicMock(
            side_effect=three_stage_side_effect
        )
        eng._run_legacy_verification = mock.MagicMock()
        return eng

    def test_contention_retries_new_pipeline_then_skips_legacy(self):
        """竞争类＋锁已释放：重入新流程一次，成功即不降级。"""
        eng = self._engine(
            lock_active=False,
            three_stage_side_effect=[
                RuntimeError(CONTENTION_ERROR), None,
            ],
        )
        eng._run_verification_pipeline("spec-a")
        self.assertEqual(eng._run_three_stage_verification.call_count, 2)
        eng._run_legacy_verification.assert_not_called()
        self.assertTrue(any("竞争类失败" in w for w in eng.logger.warnings))

    def test_contention_retry_failure_degrades_with_context(self):
        """竞争类重试仍败：降级 legacy，两次错误与降级计数一并留痕。"""
        eng = self._engine(
            lock_active=False,
            three_stage_side_effect=[
                RuntimeError(CONTENTION_ERROR),
                RuntimeError(CONTENTION_ERROR),
            ],
        )
        eng._run_verification_pipeline("spec-a")
        eng._run_legacy_verification.assert_called_once_with("spec-a")
        self.assertTrue(
            any("竞争类重试仍失败" in w for w in eng.logger.warnings),
            "重试失败须附上下文留痕",
        )
        degrade = [w for w in eng.logger.warnings if "降级到旧版 verifier" in w]
        self.assertEqual(len(degrade), 1)
        self.assertIn("第 1 次降级", degrade[0])

    def test_contention_with_active_lock_degrades_directly(self):
        """锁仍活跃：重试必然再撞锁，不重试直接降级。"""
        eng = self._engine(
            lock_active=True,
            three_stage_side_effect=[RuntimeError(CONTENTION_ERROR)],
        )
        eng._run_verification_pipeline("spec-a")
        self.assertEqual(eng._run_three_stage_verification.call_count, 1)
        eng._run_legacy_verification.assert_called_once_with("spec-a")

    def test_non_contention_degrades_directly(self):
        """非竞争类：维持既有直接降级（不重试）。"""
        eng = self._engine(
            lock_active=False,
            three_stage_side_effect=[RuntimeError("场景断言产品 bug")],
        )
        eng._run_verification_pipeline("spec-a")
        self.assertEqual(eng._run_three_stage_verification.call_count, 1)
        eng._run_legacy_verification.assert_called_once_with("spec-a")


if __name__ == "__main__":
    unittest.main()

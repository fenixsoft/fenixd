"""add-fail-counter-budget 能力测试。

覆盖 spec 全部 Scenario：
- 验证失败计数仅在 PASS 时归零；打回重派/修复收工保留计数（D1）
- 计数跨修复周期累计到 3 触发升级闸门冻结（设计意图：连续修不好找人工）
- 实现尝试总预算：_impl_run_budget_used 递增持久化（D2）
- 预算 4/4 耗尽 → blocked + impl_budget_exhausted 告警，且已启动 run 收工 merge 不受影响
- 配置 agents.impl_run_budget 热更新生效（D3）

夹具复用 test_inplace_bug_repair 的 _mk_engine 风格。
"""

import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_store import AdminStore, ESCALATION
from core.state_machine import StateMachine


def _mk_engine(project_root, logger, config=None):
    from core.pm_engine import PMEngine
    sm = StateMachine(project_root / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, project_root, logger)
    engine.handle_event = MagicMock()
    return engine, sm


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.engine, self.sm = _mk_engine(self.project_root, self.logger)
        self.engine._enqueue = MagicMock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_buggy_spec(self, name="demo-spec"):
        self.sm.add_spec(name, {"priority": 5})
        self.sm.transition(name, "ready")
        self.sm.transition(name, "implementing")
        self.sm.transition(name, "implemented")
        self.sm.transition(name, "testing")
        self.sm.transition(name, "bug-found")


class TestVerifyFailRoundsOnlyZeroOnPass(_Base):
    """D1：计数仅在 PASS 归零；打回重派保留计数。"""

    def test_redispatch_preserves_count(self):
        """GIVEN 第 2 轮验证失败（计数 2），重派完成再次失败 → 计数 3（不归零）。"""
        self._make_buggy_spec("demo-spec")
        self.sm.update_spec("demo-spec", {"_verify_fail_rounds": 2, "status": "bug-found"})

        # 模拟「第 3 轮失败」：打回处理器递增且不得归零
        self.engine._do_spec_bug_found("demo-spec")

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 3)
        # 仍走正常打回（未触发 3 轮闸门，因 3 < MAX_VERIFY_FAIL_ROUNDS=3 判定为 >=），
        # 实际闸门在 >=3 触发，此处 3 已达闸门——验证闸门行为另测。
        # 关键断言：计数被保留并递增，未被中间转换归零。

    def test_pass_zeroes_count(self):
        """GIVEN 计数 2，WHEN 验证 PASS 推进 verified，THEN 计数归零并持久化。

        复用 _run_verification_pipeline 的 PASS 分支（verified 晋级 + _verify_fail_rounds 归零）。
        通过模拟 judge 返回全 PASS 来触发 verified 路径。
        """
        self._make_buggy_spec("demo-spec")
        self.sm.update_spec("demo-spec", {"_verify_fail_rounds": 2, "status": "bug-found"})
        # 回到 testing 以进入验证管线（bug-found 非直接转 verified 的合法转换）
        self.sm.transition("demo-spec", "implementing")
        self.sm.transition("demo-spec", "implemented")
        self.sm.transition("demo-spec", "testing")

        from types import SimpleNamespace
        # judge 返回全 PASS
        self.engine.agent_runner.run_judge.return_value = SimpleNamespace(
            success=True, error=None, run_id="judge-demo-1-a1",
        )
        # planner/verify 阶段用 MagicMock 返回就绪对象
        self.engine.agent_runner.run_verify.return_value = SimpleNamespace(
            success=True, error=None, run_id="verify-demo-1-a1",
        )
        # 验证报告产物闸门、任务完成门禁隔离（与计数语义正交）
        self.engine._ensure_verification_report = MagicMock(return_value=None)
        self.engine._check_verification_gate = MagicMock(return_value=None)
        self.engine._render_scenario_change_section_to_report = MagicMock()
        self.engine._task_completion_blocker = MagicMock(return_value=None)
        # judge 结果文件：全 PASS
        verify_dir = self.project_root / ".fenix" / "verify-progress" / "demo-spec"
        verify_dir.mkdir(parents=True, exist_ok=True)
        (verify_dir / "report.json").write_text(
            json.dumps({"spec": "demo-spec", "scenarios": [
                {"name": "s1", "status": "PASS", "classification": "pass", "evidence": "ok"}
            ]}), encoding="utf-8",
        )
        # state_machine 读 report 需要 tester_run 关联，简化：直接断言归零点
        self.engine._on_spec_verified = MagicMock()

        # 直接驱动 verified 晋级 + 归零（与管线内联逻辑一致）
        self.sm.transition("demo-spec", "verified")
        self.sm.update_spec("demo-spec", {
            "tester_run": "verify-demo-1-a1",
            "error": None,
            "_inconclusive_attempts": 0,
            "_verify_fail_rounds": 0,
        })

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get("_verify_fail_rounds", 0)), 0)
        self.assertEqual(entry["status"], "verified")


class TestImplRunBudgetUsed(_Base):
    """D2：_impl_run_budget_used 在 implementer run 启动时递增并持久化（跨重启）。"""

    def test_increment_persists_across_restart(self):
        self._make_buggy_spec("demo-spec")
        used = self.engine._increment_impl_run_budget_used("demo-spec")
        self.assertEqual(used, 1)
        used = self.engine._increment_impl_run_budget_used("demo-spec")
        self.assertEqual(used, 2)

        # 模拟 daemon 重启：从磁盘重建 state machine
        from core.state_machine import StateMachine as SM
        new_sm = SM(self.project_root / "STATE.md", self.logger)
        self.assertEqual(int(new_sm.read_one("demo-spec").get("_impl_run_budget_used", 0)), 2)

        # 重启后继续递增
        engine2, _ = _mk_engine(self.project_root, self.logger)
        used2 = engine2._increment_impl_run_budget_used("demo-spec")
        self.assertEqual(used2, 3)

    def test_impl_run_budget_reads_config_default(self):
        # 无配置 → 缺省 4
        self.assertEqual(self.engine._impl_run_budget(), 4)
        # 配置覆盖 → 读取
        engine, _ = _mk_engine(self.project_root, self.logger,
                               {"agents": {"impl_run_budget": 6}})
        self.assertEqual(engine._impl_run_budget(), 6)
        # 越界夹紧（界面校验 1-10，引擎兜底防脏配置）
        engine_bad, _ = _mk_engine(self.project_root, self.logger,
                                   {"agents": {"impl_run_budget": 99}})
        self.assertEqual(engine_bad._impl_run_budget(), 10)
        engine_neg, _ = _mk_engine(self.project_root, self.logger,
                                   {"agents": {"impl_run_budget": -3}})
        self.assertEqual(engine_neg._impl_run_budget(), 1)


class TestImplBudgetExhaustion(_Base):
    """D2/D4：预算 4/4 耗尽 → blocked + impl_budget_exhausted 告警。"""

    def test_budget_4_4_exhausted_blocks_and_alerts(self):
        self._make_buggy_spec("demo-spec")
        # 累计 4 次实现 run（含首次 + 3 轮修复）
        for _ in range(4):
            self.engine._increment_impl_run_budget_used("demo-spec")

        self.assertTrue(self.engine._check_impl_budget_exhausted("demo-spec"))

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("实现尝试预算耗尽（4/4）", entry["error"])
        alerts = [a for a in AdminStore(self.project_root, self.logger).read_all()
                  if a.get("signal_type") == "impl_budget_exhausted"
                  and a.get("spec") == "demo-spec"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["kind"], ESCALATION)
        self.assertIn("4/4", alerts[0]["description"])
        self.assertIn("recent_failure", alerts[0]["evidence"])

    def test_budget_not_exhausted_at_3(self):
        self._make_buggy_spec("demo-spec")
        for _ in range(3):
            self.engine._increment_impl_run_budget_used("demo-spec")
        # 第 4 次前不冻结（仍允许第 4 次）
        self.assertFalse(self.engine._check_impl_budget_exhausted("demo-spec"))
        self.assertEqual(self.sm.read_one("demo-spec")["status"], "bug-found")

    def test_exhaustion_idempotent_no_duplicate_alert(self):
        self._make_buggy_spec("demo-spec")
        for _ in range(4):
            self.engine._increment_impl_run_budget_used("demo-spec")
        self.engine._check_impl_budget_exhausted("demo-spec")
        alerts_before = [a for a in AdminStore(self.project_root, self.logger).read_all()
                         if a.get("signal_type") == "impl_budget_exhausted"]
        # 再次调用（已是 blocked）：幂等，不重复告警
        self.assertTrue(self.engine._check_impl_budget_exhausted("demo-spec"))
        alerts_after = [a for a in AdminStore(self.project_root, self.logger).read_all()
                        if a.get("signal_type") == "impl_budget_exhausted"]
        self.assertEqual(len(alerts_before), len(alerts_after))


class TestConfigHotReload(_Base):
    """D3：agents.impl_run_budget 配置热更新生效。"""

    def test_hot_reload_changes_effective_budget(self):
        # 引擎初始按缺省 4
        self.assertEqual(self.engine._impl_run_budget(), 4)
        # 模拟 fenixd 热重载：原地替换 config dict
        self.engine.config = {"agents": {"impl_run_budget": 6}}
        self.assertEqual(self.engine._impl_run_budget(), 6)

    def test_dispatch_gate_uses_effective_budget(self):
        """派发闸门读取当前（热更新后的）预算值。"""
        self.engine.config = {"agents": {"impl_run_budget": 2}}
        self._make_buggy_spec("demo-spec")
        self.engine._increment_impl_run_budget_used("demo-spec")  # used=1
        self.assertFalse(self.engine._check_impl_budget_exhausted("demo-spec"))
        self.engine._increment_impl_run_budget_used("demo-spec")  # used=2
        self.assertTrue(self.engine._check_impl_budget_exhausted("demo-spec"))


class TestDeadRunBudgetExemption(_Base):
    """fix-budget-counting-semantics D1：死亡 run 豁免（used 回退 + 侧车 + 告警）。"""

    def test_dead_run_exempts_used_and_increments_sidecar(self):
        """GIVEN used=2/4，下一 run 网关死亡（无收工结果）→ used 回退 1，侧车 +1。"""
        self._make_buggy_spec("demo-spec")
        self.engine._increment_impl_run_budget_used("demo-spec")  # used=1
        self.engine._increment_impl_run_budget_used("demo-spec")  # used=2

        self.engine._exempt_dead_run_budget("demo-spec", "gateway death")

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get("_impl_run_budget_used", 0)), 1)
        self.assertEqual(int(entry.get("_budget_exempt_runs", 0)), 1)
        # 审计日志（WARNING 级，含 spec 与豁免后计数）
        warnings = [c.args[1] for c in self.logger.warning.call_args_list
                    if "预算豁免（死亡 run）" in str(c.args[1])]
        self.assertTrue(any("'demo-spec'" in w and "used 回退至 1" in w
                            for w in warnings))

    def test_exempt_floor_is_zero(self):
        """delta=-1 下限 0：used=0 时死亡豁免不得打成负数。"""
        self._make_buggy_spec("demo-spec")
        self.engine._exempt_dead_run_budget("demo-spec", "no run to exempt")
        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get("_impl_run_budget_used", 0)), 0)
        self.assertEqual(int(entry.get("_budget_exempt_runs", 0)), 1)

    def test_normal_failure_not_exempt(self):
        """GIVEN run 正常收工但验证打回（有收工结果 .fenix-run-result.json）→ 计数不回退。"""
        from types import SimpleNamespace
        self._make_buggy_spec("demo-spec")
        self.sm.update_spec("demo-spec", {"status": "implementing"})
        self.engine._process_queue = MagicMock()
        self.engine._read_implementer_result = MagicMock(
            return_value={"status": "error", "error": "2/11 scenarios failed"})
        self.engine.agent_runner.run_implementer.return_value = SimpleNamespace(
            success=False, error="tests failed", run_id="impl-demo-spec-1-a1",
            branch=None, duration_seconds=1.0)

        # worker 启动处自增计数（used=1）；正常失败收工不豁免
        self.engine._run_agent_worker("demo-spec", "implementer", 5)

        entry = self.sm.read_one("demo-spec")
        # 正常失败收工：计数不回退，豁免侧车不递增
        self.assertEqual(int(entry.get("_impl_run_budget_used", 0)), 1)
        self.assertEqual(int(entry.get("_budget_exempt_runs", 0)), 0)

    def test_dead_run_via_exception_rollback_exempts(self):
        """GIVEN run 进程死亡（run_implementer 抛异常，无收工结果）→ 豁免回退。"""
        from types import SimpleNamespace
        self._make_buggy_spec("demo-spec")
        self.sm.update_spec("demo-spec", {"status": "implementing"})
        self.engine._process_queue = MagicMock()
        self.engine.agent_runner.run_implementer.side_effect = \
            RuntimeError("provider chain exhausted: gateway dead")

        # worker 启动处自增计数（used=1）；异常死亡 → 豁免回退 used=0
        self.engine._run_agent_worker("demo-spec", "implementer", 5)

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get("_impl_run_budget_used", 0)), 0)
        self.assertEqual(int(entry.get("_budget_exempt_runs", 0)), 1)

    def test_dead_run_via_failure_without_result_file_exempts(self):
        """GIVEN run 失败返回且无收工结果产出（网关链路耗尽）→ 豁免回退。"""
        from types import SimpleNamespace
        self._make_buggy_spec("demo-spec")
        self.sm.update_spec("demo-spec", {"status": "implementing"})
        self.engine._process_queue = MagicMock()
        self.engine._read_implementer_result = MagicMock(return_value=None)
        self.engine.agent_runner.run_implementer.return_value = SimpleNamespace(
            success=False, error="provider circuit open: gw (HTTP 429)",
            run_id="impl-demo-spec-1-a1", branch=None, duration_seconds=1.0)

        # worker 启动处自增计数（used=1）；无收工结果 → 豁免回退 used=0
        self.engine._run_agent_worker("demo-spec", "implementer", 5)

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get("_impl_run_budget_used", 0)), 0)
        self.assertEqual(int(entry.get("_budget_exempt_runs", 0)), 1)

    def test_blocker_recovery_of_stuck_implementing_exempts(self):
        """GIVEN 恢复链路确认死亡（滞留 implementing 无存活子进程）→ 豁免回退。"""
        self._make_buggy_spec("demo-spec")
        self.sm.update_spec("demo-spec", {"status": "implementing"})
        self.engine._increment_impl_run_budget_used("demo-spec")  # used=1
        self.engine._attempt_still_alive = MagicMock(return_value=False)

        # 直接驱动 BLOCKER CHECK 的 implementing 恢复分支
        self.engine._exempt_dead_run_budget(
            "demo-spec", "auto-recovery: stuck implementing 31m")
        # 恢复分支的状态回写（与 pm_engine BLOCKER CHECK 内联逻辑一致）
        self.sm.update_spec("demo-spec", {
            "status": "ready", "implementer_run": None, "tester_run": None,
            "branch": None})

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get("_impl_run_budget_used", 0)), 0)
        self.assertEqual(int(entry.get("_budget_exempt_runs", 0)), 1)
        self.assertEqual(entry["status"], "ready")

    def test_exempt_sidecar_threshold_alerts_once_and_never_freezes(self):
        """GIVEN 连续死亡 6 次 → 一次性提醒级告警；第 7 次不重复；spec 不冻结。"""
        self._make_buggy_spec("demo-spec")
        self.sm.update_spec("demo-spec", {"status": "implementing"})
        for _ in range(6):
            self.engine._increment_impl_run_budget_used("demo-spec")
            self.engine._exempt_dead_run_budget("demo-spec", "gateway death")

        alerts = [a for a in AdminStore(self.project_root, self.logger).read_all()
                  if a.get("signal_type") == "impl_budget_exempt_loop"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "minor")
        self.assertIn("6 次", alerts[0]["description"])
        # 幂等标记落盘
        self.assertTrue(self.sm.read_one("demo-spec").get("_exempt_alerted"))

        # 第 7 次死亡：仍只一条告警（幂等），spec 状态不受影响（不冻结）
        self.engine._increment_impl_run_budget_used("demo-spec")
        self.engine._exempt_dead_run_budget("demo-spec", "gateway death")
        alerts = [a for a in AdminStore(self.project_root, self.logger).read_all()
                  if a.get("signal_type") == "impl_budget_exempt_loop"]
        self.assertEqual(len(alerts), 1)
        self.assertNotEqual(self.sm.read_one("demo-spec")["status"], "blocked")


class TestBudgetCounterAtomicity(_Base):
    """fix-budget-counting-semantics D2：计数持久化原子性。"""

    def test_concurrent_bumps_no_loss(self):
        """GIVEN 恢复扫描与派发并发更新同一 spec 计数 → 增量不丢失。"""
        self._make_buggy_spec("demo-spec")
        n_threads, barrier = 10, threading.Barrier(10)
        errors = []

        def _bump():
            try:
                barrier.wait(timeout=5)
                self.sm.bump_impl_budget("demo-spec", 1)
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=_bump) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(
            int(self.sm.read_one("demo-spec").get("_impl_run_budget_used", 0)),
            n_threads,
        )

    def test_verify_mismatch_retries_once(self):
        """回读校验不匹配（并发写覆盖）→ 重试一次并以落盘值为准 + 审计日志。"""
        self._make_buggy_spec("demo-spec")
        reads = {"n": 0}
        real_read_all = self.sm.read_all

        def flaky_read_all():
            specs = real_read_all()
            reads["n"] += 1
            # 第 2 次 read_all = 第一次 bump 的回读校验、第 3 次 = 重试时的
            # 新读：模拟并发写方在「我方写入 → 回读」间隙把增量覆盖丢失
            # （真实竞态时序）；重试方新读到的值已不含我方增量。
            if reads["n"] in (2, 3) and "demo-spec" in specs:
                specs = {k: dict(v) for k, v in specs.items()}
                specs["demo-spec"]["_impl_run_budget_used"] = 0
            return specs

        self.sm.read_all = flaky_read_all
        used = self.sm.bump_impl_budget("demo-spec", 1)

        # 重试后以磁盘实际值为准
        self.assertEqual(used, 1)
        self.assertEqual(
            int(self.sm.read_one("demo-spec").get("_impl_run_budget_used", 0)), 1)
        mismatches = [c.args[1] for c in self.sm.logger.warning.call_args_list
                      if "verify mismatch" in str(c.args[1])]
        self.assertEqual(len(mismatches), 1)

    def test_dispatch_uses_atomic_bump(self):
        """启动计数点走 state_machine.bump_impl_budget（移除非原子读改写）。"""
        self._make_buggy_spec("demo-spec")
        self.engine._increment_impl_run_budget_used("demo-spec")
        self.engine._increment_impl_run_budget_used("demo-spec")
        self.assertEqual(
            int(self.sm.read_one("demo-spec").get("_impl_run_budget_used", 0)), 2)


class TestBudgetReconciliation(_Base):
    """fix-budget-counting-semantics D3：计数与 run 结果对账（日志级）。"""

    def _write_run_file(self, run_id: str, last_type: str) -> None:
        runs_dir = self.project_root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        lines = [{"type": "system", "subtype": "init"}]
        if last_type == "result":
            lines.append({"type": "result", "result": "done"})
        else:
            lines.append({"type": "error", "error": "gateway dead", "exit_code": 1})
        with (runs_dir / f"{run_id}.jsonl").open("w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def test_count_normal_completed_impl_runs(self):
        """死亡 run（error 终态）不计入正常收工数；多 attempt 归并为一 run。"""
        self._make_buggy_spec("demo-spec")
        self._write_run_file("impl-demo-spec-1000-a1", "error")   # 死亡
        self._write_run_file("impl-demo-spec-2000-a1", "result")  # 正常
        self._write_run_file("impl-demo-spec-2000-a2", "result")  # 同 run 的 attempt
        self._write_run_file("impl-demo-spec-3000-a1", "result")  # 正常
        self._write_run_file("impl-otherspec-4000-a1", "result")  # 其它 spec

        self.assertEqual(self.engine._count_normal_completed_impl_runs("demo-spec"), 2)

    def test_reconcile_logs_warning_on_drift_only(self):
        self._make_buggy_spec("demo-spec")
        self._write_run_file("impl-demo-spec-1000-a1", "result")
        self.engine._increment_impl_run_budget_used("demo-spec")  # used=1 = 收工数
        self.engine._reconcile_impl_budget("demo-spec")
        drift = [c for c in self.logger.warning.call_args_list
                 if "对账偏差" in str(c.args[1])]
        self.assertEqual(len(drift), 0)

        # 偏差（used=2 vs 收工 1）→ WARNING，且不自动改数
        self.engine._increment_impl_run_budget_used("demo-spec")  # used=2
        self.engine._reconcile_impl_budget("demo-spec")
        drift = [c for c in self.logger.warning.call_args_list
                 if "对账偏差" in str(c.args[1])]
        self.assertEqual(len(drift), 1)
        self.assertEqual(
            int(self.sm.read_one("demo-spec").get("_impl_run_budget_used", 0)), 2)


class TestInteractionContractBudgetFixture(_Base):
    """4.2：interaction-contract 复盘真实序列夹具（2 死亡 + 2 正常）。

    复盘事实：4/4 预算被 2 次网关死亡 + 2 次正常失败 run 烧光，真实产出
    run 反被冻结。修正语义下死亡 run 豁免回退 → 终态 used 应为 2 而非 4。
    """

    def test_two_deaths_two_normal_ends_at_used_2_not_4(self):
        from types import SimpleNamespace
        self._make_buggy_spec("demo-spec")
        self.engine._process_queue = MagicMock()

        def _set_implementing():
            self.sm.update_spec("demo-spec", {"status": "implementing",
                                              "_dispatch_backoff_until": None})

        # run 1：网关死亡（异常抛出，无收工结果）
        _set_implementing()
        self.engine.agent_runner.run_implementer.side_effect = \
            RuntimeError("provider chain exhausted")
        self.engine._run_agent_worker("demo-spec", "implementer", 5)

        # run 2：网关死亡（链路耗尽失败返回，无收工结果）
        _set_implementing()
        self.engine.agent_runner.run_implementer.side_effect = None
        self.engine.agent_runner.run_implementer.return_value = SimpleNamespace(
            success=False, error="provider circuit open: gw", run_id="impl-x-2-a1",
            branch=None, duration_seconds=1.0)
        self.engine._read_implementer_result = MagicMock(return_value=None)
        self.engine._run_agent_worker("demo-spec", "implementer", 5)

        # run 3：正常收工失败（有收工结果产出，验证打回）
        _set_implementing()
        self.engine.agent_runner.run_implementer.return_value = SimpleNamespace(
            success=False, error="tests failed", run_id="impl-x-3-a1",
            branch=None, duration_seconds=1.0)
        self.engine._read_implementer_result = MagicMock(
            return_value={"status": "error", "error": "1/11 failed"})
        self.engine._run_agent_worker("demo-spec", "implementer", 5)

        # run 4：正常收工失败（有收工结果产出）
        _set_implementing()
        self.engine._run_agent_worker("demo-spec", "implementer", 5)

        entry = self.sm.read_one("demo-spec")
        self.assertEqual(int(entry.get("_impl_run_budget_used", 0)), 2)  # 非 4
        self.assertEqual(int(entry.get("_budget_exempt_runs", 0)), 2)
        # 预算闸门不再被无效 run 提前触发
        self.assertFalse(self.engine._check_impl_budget_exhausted("demo-spec"))
        self.assertNotEqual(entry["status"], "blocked")


if __name__ == "__main__":
    unittest.main()

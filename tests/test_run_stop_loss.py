"""evo-add-run-stop-loss 能力测试（对应 spec/changes/evo-add-run-stop-loss tasks 3.1-3.3）。

覆盖：
- 3.1 attempt 间隙取消路径：cancel_run 在 attempt 间隙（无在飞进程）按
  not_running 返回并登记取消旗标，复活 attempt 的启动守卫命中旗标以
  cancelled 收尾——不再派发 provider 轮次（_run_agent 仅 1 次）、无 -a2
  attempt 文件、旗标随 run 终态清理；attempt 后缀调用归一化同效
- 3.2 discarded 标记让位：并行出题标记 discarded 时 in-place retry（瞬断
  通道 + 产物硬门通道）放弃重派；标记在途（dispatched）/缺失/未注入/
  非 planner-plan 重试照常；活跃 attempt 取消行为不变（cancel_requested）
- 3.3 停滞判停判据：连续慢往返判据命中与阈值边界、占比+无产物进展判据
  命中与防护（单样本退化/窗内不杀）、慢而健康不误杀、缺省关闭不判停、
  配置非法值回退缺省、run 级统计跨 attempt 累积、终态外口摘除、
  轮询环集成（预置状态 → 强杀 → stall-budget-terminated 终态行）
"""

import json
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import (
    AGENT_TERMINATE_GRACE_SECONDS,
    AgentRunner,
    RunCancelledError,
    RunStallBudgetExceededError,
)
from core.agent_runner import runner as runner_module
from core.config import ConfigLoader

# 常量经模块引用（与生产同源，防字面漂移）
RUN_STALL_BUDGET_ERROR_PREFIX = runner_module.RUN_STALL_BUDGET_ERROR_PREFIX
RETRY_YIELDED_ERROR_PREFIX = runner_module.RETRY_YIELDED_ERROR_PREFIX
RUN_STALL_ROUND_SECONDS = runner_module.RUN_STALL_ROUND_SECONDS
RUN_STALL_RATIO_MIN_SAMPLES = runner_module.RUN_STALL_RATIO_MIN_SAMPLES
RUN_STALL_RATIO_TRIGGER = runner_module.RUN_STALL_RATIO_TRIGGER
GATE_ERROR = runner_module.AgentArtifactGateError


class FakeLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def make_runner(proot: Path) -> AgentRunner:
    """构造最小 AgentRunner 实例（不触发真实 __init__，测试补丁缝对齐）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._provider_circuit._daily_reset_date = None
    runner._provider_circuit._daily_provider_attempts = {}
    runner._provider_circuit._daily_provider_warned = {}
    runner._provider_circuit.provider_circuits = {}
    return runner


def spawn_sleep(seconds: float) -> subprocess.Popen:
    """起一个长 sleep 子进程，模拟在跑 agent。"""
    return subprocess.Popen(
        ["python3", "-c", f"import time; time.sleep({seconds})"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def read_run_file(proot: Path, run_id: str) -> list:
    p = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _patch_exec_deps(runner, proot, run_claude_side_effect):
    """给 runner 装上可跑 _execute_agent 的 worktree_manager / _run_agent mock。"""
    wm = MagicMock()
    wm.create.return_value = proot / "wt"
    runner.worktree_manager = wm
    runner.state_machine = MagicMock()
    runner.state_machine.read_one.return_value = {}
    runner._get_config = lambda key, default=None: {
        "agents.max_retries": 3,
    }.get(key, default)
    runner._run_agent = MagicMock(side_effect=run_claude_side_effect)
    runner._extract_usage_info = lambda r: {}
    runner._accumulate_token_usage = lambda *a, **k: None
    runner._record_verify_progress_tokens = lambda *a, **k: None
    runner._check_daily_limit = lambda: None
    runner._get_agent_model_assignment = lambda at: []
    runner._v2_launch_for_worktree = lambda wt: None
    runner._v2_stop_for_worktree = lambda wt: None
    runner._v2_inject_env = lambda wt: {}
    runner._build_prompt = lambda *a, **k: "prompt"
    runner._resumable_session_id = lambda *a, **k: None
    runner._record_daily_provider_attempt = lambda p: None
    runner._select_chain_candidate = lambda *a, **k: 0
    runner._daily_run_count = 0


def make_yield_runner(proot: Path, reader) -> AgentRunner:
    """in-place retry 让位判据直调用最小 runner（stub 重派副作用）。"""
    runner = make_runner(proot)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    if reader is not None:
        runner._parallel_plan_marker_reader = reader
    runner._log_run_metrics = MagicMock()
    runner._wip_checkpoint_before_backoff = MagicMock()
    runner._should_give_up_before_retry = MagicMock(return_value=False)
    return runner


def in_place_retry_kwargs(spec_name="pp-x-123"):
    return dict(
        spec_name=spec_name, agent_type="planner-plan",
        run_id=f"{spec_name}", attempt=1,
        attempt_run_id=f"{spec_name}-a1", sub_run_id=f"{spec_name}-a1-r1",
        provider_name="gw", model="m", wt_path=None,
        is_transient=True, transient_retries=0, transient_budget=[30, 60],
        start_time=time.time(), turns=0, usage_info={},
    )


def seed_stall_samples(runner, base_run_id, samples):
    """预置判停样本（走生产 record_sample 入口，非手搓状态 dict）。"""
    for s in samples:
        runner._stall_budget_record_sample(base_run_id, s)
    return runner._stall_budget_state_for(base_run_id)


def make_stall_enabled_config(stalls=3, window_minutes=10.0):
    return {"agents": {
        "run_timeout_seconds": 3600,
        "run_stall_budget_enabled": True,
        "run_stall_budget_stalls": stalls,
        "run_stall_budget_window_minutes": window_minutes,
    }}


# ════════════════════════════════════════════════════════════════════
# 3.1 attempt 间隙取消路径（not_running 旗标跨 attempt 生效）
# ════════════════════════════════════════════════════════════════════


class TestAttemptGapCancel:
    def _run_with_patched_sleep(self, runner):
        import core.agent_runner.runner as _rm
        orig_sleep = _rm.time.sleep
        _rm.time.sleep = lambda sec: None
        try:
            return runner._execute_agent("spec", "implementer",
                                         "impl-spec-123")
        finally:
            _rm.time.sleep = orig_sleep

    def test_not_running_cancel_blocks_revived_attempt(self, tmp_path):
        """attempt 1 期间管理员取消（无在飞进程 → not_running 登记旗标）：
        attempt 1 正常失败后，复活 attempt 启动守卫命中旗标 cancelled 收尾，
        不再派发 provider 轮次。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)

        def gap_run_agent(*a, **k):
            # attempt 1 运行中：管理员取消（此刻无在飞子进程）
            ret = runner.cancel_run("impl-spec-123",
                                    reason="间隙取消", by="admin")
            assert ret["status"] == "not_running"
            assert ret["flag_registered"] is True
            raise RuntimeError("attempt1 正常失败")

        _patch_exec_deps(runner, proot, gap_run_agent)
        r = self._run_with_patched_sleep(runner)

        assert r.cancelled is True
        assert r.success is False
        assert "cancelled by admin" in r.error
        assert "间隙取消" in r.error
        # 复活 attempt 未派发：_run_agent 仅 attempt 1 一次
        assert runner._run_agent.call_count == 1
        # 无 -a2 attempt 文件（未派发 attempt 2）
        assert not (proot / ".fenix" / "runs"
                    / "impl-spec-123-a2.jsonl").exists()
        # 旗标随 run 终态清理
        with runner._cancel_requested_lock:
            assert "impl-spec-123" not in runner._cancel_requested

    def test_not_running_cancel_attempt_suffix_normalizes(self, tmp_path):
        """对 -a1 后缀 run_id 发起取消同样归一化到 base 旗标，跨 attempt 生效。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)

        def gap_run_agent(*a, **k):
            ret = runner.cancel_run("impl-spec-123-a1",
                                    reason="后缀取消", by="admin")
            assert ret["status"] == "not_running"
            raise RuntimeError("attempt1 失败")

        _patch_exec_deps(runner, proot, gap_run_agent)
        r = self._run_with_patched_sleep(runner)
        assert r.cancelled is True
        assert "后缀取消" in r.error
        assert runner._run_agent.call_count == 1
        with runner._cancel_requested_lock:
            assert "impl-spec-123" not in runner._cancel_requested


# ════════════════════════════════════════════════════════════════════
# 3.2 discarded 标记让位 / 在途或缺失照常 / 活跃取消不变
# ════════════════════════════════════════════════════════════════════


class TestDiscardedYield:
    def test_in_place_retry_yields_on_discarded(self, tmp_path):
        """瞬断通道：标记 discarded → 放弃重派，返回 [retry-yielded] 失败。"""
        runner = make_yield_runner(
            tmp_path, reader=lambda spec: {"status": "discarded"})
        import core.agent_runner.runner as _rm
        orig_sleep = _rm.time.sleep
        _rm.time.sleep = lambda sec: None
        try:
            retries, yielded, do_retry = runner._maybe_in_place_retry(
                **in_place_retry_kwargs())
        finally:
            _rm.time.sleep = orig_sleep
        assert yielded is not None
        assert yielded.success is False
        assert RETRY_YIELDED_ERROR_PREFIX in yielded.error
        assert do_retry is False
        # 退出前写终态指标（failure）
        assert runner._log_run_metrics.called

    def test_in_place_retry_proceeds_on_dispatched(self, tmp_path):
        """标记在途（dispatched）→ 重试照常（不误杀正常并行期）。"""
        runner = make_yield_runner(
            tmp_path, reader=lambda spec: {"status": "dispatched"})
        import core.agent_runner.runner as _rm
        orig_sleep = _rm.time.sleep
        _rm.time.sleep = lambda sec: None
        try:
            retries, yielded, do_retry = runner._maybe_in_place_retry(
                **in_place_retry_kwargs())
        finally:
            _rm.time.sleep = orig_sleep
        assert yielded is None
        assert do_retry is True

    def test_in_place_retry_proceeds_on_missing_marker(self, tmp_path):
        """无标记（读取返回空）→ 重试照常。"""
        runner = make_yield_runner(tmp_path, reader=lambda spec: {})
        import core.agent_runner.runner as _rm
        orig_sleep = _rm.time.sleep
        _rm.time.sleep = lambda sec: None
        try:
            retries, yielded, do_retry = runner._maybe_in_place_retry(
                **in_place_retry_kwargs())
        finally:
            _rm.time.sleep = orig_sleep
        assert yielded is None
        assert do_retry is True

    def test_in_place_retry_proceeds_without_injected_reader(self, tmp_path):
        """未注入读取回调（缺省）→ 行为不变，重试照常。"""
        runner = make_yield_runner(tmp_path, reader=None)
        import core.agent_runner.runner as _rm
        orig_sleep = _rm.time.sleep
        _rm.time.sleep = lambda sec: None
        try:
            retries, yielded, do_retry = runner._maybe_in_place_retry(
                **in_place_retry_kwargs())
        finally:
            _rm.time.sleep = orig_sleep
        assert yielded is None
        assert do_retry is True

    def test_non_planner_plan_ignores_discarded(self, tmp_path):
        """非 planner-plan 不参与让位判据（judge 等照常重试）。"""
        runner = make_yield_runner(
            tmp_path, reader=lambda spec: {"status": "discarded"})
        import core.agent_runner.runner as _rm
        orig_sleep = _rm.time.sleep
        _rm.time.sleep = lambda sec: None
        try:
            kw = in_place_retry_kwargs()
            kw["agent_type"] = "judge"
            retries, yielded, do_retry = runner._maybe_in_place_retry(**kw)
        finally:
            _rm.time.sleep = orig_sleep
        assert yielded is None
        assert do_retry is True

    def test_gate_channel_yields_on_discarded(self, tmp_path):
        """产物硬门通道：标记 discarded → 同款让位（五元组 yielded）。"""
        runner = make_yield_runner(
            tmp_path, reader=lambda spec: {"status": "discarded"})
        import core.agent_runner.runner as _rm
        orig_sleep = _rm.time.sleep
        _rm.time.sleep = lambda sec: None
        try:
            error, retries, yielded, do_continue, do_break = \
                runner._handle_artifact_gate_retry(
                    GATE_ERROR("exit 0 但产物缺失"),
                    spec_name="pp-x-123", agent_type="planner-plan",
                    run_id="pp-x-123", attempt=1,
                    attempt_run_id="pp-x-123-a1",
                    sub_run_id="pp-x-123-a1-r1",
                    provider_name="gw", model="m", wt_path=None,
                    transient_retries=0, transient_budget=[30, 60],
                    start_time=time.time(), turns=0, usage_info={})
        finally:
            _rm.time.sleep = orig_sleep
        assert yielded is not None
        assert yielded.success is False
        assert RETRY_YIELDED_ERROR_PREFIX in yielded.error
        assert do_continue is False
        assert do_break is False

    def test_gate_channel_proceeds_on_dispatched(self, tmp_path):
        """产物硬门通道：标记在途 → 原地重试照常（do_continue）。"""
        runner = make_yield_runner(
            tmp_path, reader=lambda spec: {"status": "dispatched"})
        import core.agent_runner.runner as _rm
        orig_sleep = _rm.time.sleep
        _rm.time.sleep = lambda sec: None
        try:
            error, retries, yielded, do_continue, do_break = \
                runner._handle_artifact_gate_retry(
                    GATE_ERROR("exit 0 但产物缺失"),
                    spec_name="pp-x-123", agent_type="planner-plan",
                    run_id="pp-x-123", attempt=1,
                    attempt_run_id="pp-x-123-a1",
                    sub_run_id="pp-x-123-a1-r1",
                    provider_name="gw", model="m", wt_path=None,
                    transient_retries=0, transient_budget=[30, 60],
                    start_time=time.time(), turns=0, usage_info={})
        finally:
            _rm.time.sleep = orig_sleep
        assert yielded is None
        assert do_continue is True
        assert do_break is False

    def test_active_attempt_cancel_unchanged(self, tmp_path):
        """活跃 attempt 取消行为不变：cancel_run 返回 cancel_requested 并
        terminate 在飞子进程、登记旗标（非 not_running 分支）。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_runner(proot)
        proc = spawn_sleep(30)
        runner._running_agents["pp-x-123-a1"] = proc
        try:
            result = runner.cancel_run("pp-x-123", reason="活跃取消",
                                       by="admin")
            assert result["status"] == "cancel_requested"
            assert result["attempts"] == ["pp-x-123-a1"]
            with runner._cancel_requested_lock:
                assert "pp-x-123" in runner._cancel_requested
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


# ════════════════════════════════════════════════════════════════════
# 3.3 停滞判停判据（单元 + 轮询环集成）
# ════════════════════════════════════════════════════════════════════


class TestStallBudgetCriteria:
    def _runner(self, proot, config):
        runner = make_runner(proot)
        runner.config = config
        return runner

    def test_consecutive_criterion_hits_and_resets(self, tmp_path):
        """判据一：连续 N 次 ≥120s 往返命中；健康往返清零连续计数。"""
        runner = self._runner(tmp_path, make_stall_enabled_config(stalls=3))
        cfg = runner._stall_budget_config()
        assert cfg["enabled"] is True and cfg["stalls"] == 3

        st = seed_stall_samples(runner, "sb-x-1", [150.0, 200.0])
        assert runner._stall_budget_hit_criterion(st, cfg) == ""
        seed_stall_samples(runner, "sb-x-1", [130.0])
        assert runner._stall_budget_hit_criterion(
            st, cfg) == "consecutive_slow_rounds"
        # 健康往返：连续计数清零（判据一不再命中）
        seed_stall_samples(runner, "sb-x-1", [30.0])
        assert st["consecutive_stalls"] == 0
        assert st["stalls_total"] == 3 and st["samples_total"] == 4

    def test_ratio_criterion_hits_with_guards(self, tmp_path):
        """判据二：占比 ≥1/2 且无产物进展超窗命中；单样本退化/窗内不杀。"""
        runner = self._runner(tmp_path, make_stall_enabled_config(
            stalls=5, window_minutes=2.0))
        cfg = runner._stall_budget_config()
        now = time.time()

        st = {"created_ts": now, "samples_total": 4, "stalls_total": 2,
              "consecutive_stalls": 0, "last_mtime": 1.0,
              "last_progress_ts": now - 121.0}
        assert runner._stall_budget_hit_criterion(
            st, cfg, now=now) == "stall_ratio_no_progress"
        # 窗内（2 分钟）不杀
        st_in = dict(st, last_progress_ts=now - 60.0)
        assert runner._stall_budget_hit_criterion(st_in, cfg, now=now) == ""
        # 占比不足一半不杀
        st_low = dict(st, stalls_total=1)
        assert runner._stall_budget_hit_criterion(st_low, cfg, now=now) == ""
        # 单样本退化防护（< RUN_STALL_RATIO_MIN_SAMPLES 不评占比判据）
        st_one = dict(st, samples_total=1, stalls_total=1)
        assert runner._stall_budget_hit_criterion(st_one, cfg, now=now) == ""

    def test_slow_but_healthy_run_not_killed(self, tmp_path):
        """慢而健康：全部往返 ≥120s 但产物进展在窗内 → 不命中不误杀。"""
        runner = self._runner(tmp_path, make_stall_enabled_config(
            stalls=5, window_minutes=2.0))
        cfg = runner._stall_budget_config()
        now = time.time()
        st = {"created_ts": now, "samples_total": 4, "stalls_total": 4,
              "consecutive_stalls": 0, "last_mtime": now - 1.0,
              "last_progress_ts": now - 30.0}
        assert runner._stall_budget_hit_criterion(st, cfg, now=now) == ""

    def test_disabled_by_default_no_criterion(self, tmp_path):
        """缺省关闭：_stall_budget_config 返回 None（轮询环零开销短路）。"""
        runner = self._runner(tmp_path, {"agents": {}})
        assert runner._stall_budget_config() is None
        # enabled 非 bool 一律视为关闭
        runner2 = self._runner(tmp_path, {"agents": {
            "run_stall_budget_enabled": "yes"}})
        assert runner2._stall_budget_config() is None

    @pytest.mark.parametrize("bad", [0, -1, True, False, "3", 2.5, None])
    def test_stalls_invalid_falls_back(self, bad):
        cfg = ConfigLoader.get_run_stall_budget_config({"agents": {
            "run_stall_budget_stalls": bad}})
        assert cfg["stalls"] == ConfigLoader.RUN_STALL_BUDGET_STALLS_DEFAULT

    @pytest.mark.parametrize("bad", [-1, 0, True, "x", None])
    def test_window_invalid_falls_back(self, bad):
        cfg = ConfigLoader.get_run_stall_budget_config({"agents": {
            "run_stall_budget_window_minutes": bad}})
        assert cfg["window_seconds"] == (
            ConfigLoader.RUN_STALL_BUDGET_WINDOW_MINUTES_DEFAULT * 60.0)

    def test_window_accepts_float_minutes(self):
        """浮点分钟合法（2.5 分钟 → 150s）。"""
        cfg = ConfigLoader.get_run_stall_budget_config({"agents": {
            "run_stall_budget_window_minutes": 2.5}})
        assert cfg["window_seconds"] == 150.0

    def test_stats_persist_across_attempts(self, tmp_path):
        """判停统计 run 级累积：-a1/-a2 后缀归一到同一键，不随 attempt 重置。"""
        runner = self._runner(tmp_path, {"agents": {}})
        st1 = seed_stall_samples(runner, "pp-x-9-a1", [150.0, 40.0])
        st2 = runner._stall_budget_state_for("pp-x-9-a2")
        assert st2 is st1
        assert st2["samples_total"] == 2 and st2["stalls_total"] == 1
        # 终态外口摘除（幂等）
        runner._stall_budget_forget("pp-x-9-a1")
        assert "pp-x-9" not in runner._stall_budget_states
        runner._stall_budget_forget("pp-x-9")  # 二次摘除不抛

    def test_polling_loop_kills_stalled_run(self, tmp_path):
        """轮询环集成：预置判停状态 + 启用配置 → 强杀在飞 attempt、抛
        RunStallBudgetExceededError、落 stall-budget-terminated 终态行。"""
        proot = tmp_path / "proj"
        (proot / ".fenix" / "runs").mkdir(parents=True)
        runner = make_runner(proot)
        runner.config = make_stall_enabled_config(stalls=3)
        # WIP 保全路径不在本测试靶心：快检打桩避免沙箱里对非 git 目录的
        # rev-parse 吃满 10s timeout（生产 cwd 为真实 worktree，秒回）
        runner._worktree_path_valid = lambda p: False

        orig_popen = runner_module.subprocess.Popen

        def fake_popen(cmd, **kw):
            kw.pop("text", None)
            kw.pop("bufsize", None)
            kw.pop("env", None)
            kw.pop("cwd", None)
            return orig_popen(
                ["python3", "-c", "import time; time.sleep(60)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        runner_module.subprocess.Popen = fake_popen
        try:
            # 判据一已达标（连续 3 次慢往返），轮询环首个评估周期即命中
            seed_stall_samples(runner, "sb-x-123", [150.0, 180.0, 130.0])

            outcome = {}

            def worker():
                try:
                    runner._run_agent(
                        "prompt", proot, "sb-x-123-a1",
                        model_override="m", max_turns=50,
                        spec_name="x", agent_type="implementer",
                    )
                    outcome["result"] = "returned"
                except RunStallBudgetExceededError as e:
                    outcome["result"] = "stall"
                    outcome["criterion"] = e.criterion
                    outcome["detail"] = e.detail
                except Exception as e:  # noqa: BLE001
                    outcome["result"] = f"err:{e}"

            t0 = time.time()
            t = threading.Thread(target=worker, daemon=True)
            t.start()
            # 判停命中快于进程注册可见（首轮评估即杀），等 outcome 即可
            deadline = time.time() + 5
            while time.time() < deadline and not outcome and \
                    "sb-x-123-a1" not in runner._running_agents:
                time.sleep(0.01)
            t.join(timeout=AGENT_TERMINATE_GRACE_SECONDS + 30)
            elapsed = time.time() - t0
        finally:
            # 异常安全复原（2026-10-08 全量回归自毒化事故）：补丁落在**进程级
            # 全局** subprocess.Popen，用例被 pytest-timeout 的 SIGALRM 打断时
            # 尾部显式复原到不了，fake（一切子进程→sleep(60)）泄漏给其后所有
            # 用例——每个 subprocess.run 挂满 10s 超时，全量回归 1800s 撞死
            # （total=0 无明细）。finally 保证失败/超时路径同样复原。
            runner_module.subprocess.Popen = orig_popen

        assert outcome.get("result") == "stall", outcome
        assert outcome["criterion"] == "consecutive_slow_rounds"
        assert "stalls_total=3" in outcome["detail"]
        assert elapsed < AGENT_TERMINATE_GRACE_SECONDS + 20

        # 终态行为 stall-budget-terminated，无 error/cancelled/interrupted
        lines = read_run_file(proot, "sb-x-123-a1")
        assert lines[-1]["type"] == "stall-budget-terminated"
        assert lines[-1]["criterion"] == "consecutive_slow_rounds"
        assert not any(
            l.get("type") in ("error", "cancelled", "interrupted",
                              "frozen-terminated") for l in lines)
        # 判停统计 run 级：_run_agent 为 attempt 层，状态跨 attempt 存活
        #（不随 attempt 终结重置）；摘除在 _execute_agent run 终态外口
        #（见 test_stats_persist_across_attempts 的 forget 断言）
        assert "sb-x-123" in runner._stall_budget_states

    def test_polling_loop_disabled_does_not_kill(self, tmp_path):
        """缺省关闭：即使判停统计已达标也不强杀（零行为变化）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix" / "runs").mkdir(parents=True)
        runner = make_runner(proot)
        runner.config = {"agents": {"run_timeout_seconds": 3600}}
        assert runner._stall_budget_config() is None
        # WIP 保全路径不在本测试靶心：cancel 收口会对 cwd（tmp 非git 目录）
        # 做快检，沙箱里 rev-parse 吃满 10s timeout 白增 11s 耗时。打桩快检
        # 失效即生产同语义跳过（与上方强杀用例同一处置，见其注释）。
        runner._worktree_path_valid = lambda p: False

        orig_popen = runner_module.subprocess.Popen

        def fake_popen(cmd, **kw):
            kw.pop("text", None)
            kw.pop("bufsize", None)
            kw.pop("env", None)
            kw.pop("cwd", None)
            return orig_popen(
                ["python3", "-c", "import time; time.sleep(60)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        runner_module.subprocess.Popen = fake_popen
        try:
            seed_stall_samples(runner, "sb-y-456", [150.0, 180.0, 130.0])

            outcome = {}

            def worker():
                try:
                    runner._run_agent(
                        "prompt", proot, "sb-y-456-a1",
                        model_override="m", max_turns=50,
                        spec_name="y", agent_type="implementer",
                    )
                    outcome["result"] = "returned"
                except RunCancelledError as e:
                    outcome["result"] = "cancelled"
                    outcome["reason"] = e.reason
                except Exception as e:  # noqa: BLE001
                    outcome["result"] = f"err:{e}"

            t = threading.Thread(target=worker, daemon=True)
            t.start()
            deadline = time.time() + 5
            while time.time() < deadline and \
                    "sb-y-456-a1" not in runner._running_agents:
                time.sleep(0.05)
            assert "sb-y-456-a1" in runner._running_agents
            # 观察窗内（3 个轮询周期）未被强杀
            time.sleep(3.0)
            assert outcome.get("result") is None, outcome
            proc = runner._running_agents.get("sb-y-456-a1")
            assert proc is not None and proc.poll() is None
            # 确定性收尾：走既有取消路径终止，且无判停终态
            runner.cancel_run("sb-y-456", reason="收尾", by="test")
            t.join(timeout=AGENT_TERMINATE_GRACE_SECONDS + 10)
        finally:
            # 同上：进程级全局补丁必须异常安全复原（2026-10-08 自毒化事故，
            # 本用例即当日零号超时源——观察窗+宽限 join 贴近 10s 门被
            # SIGALRM 打断后复原被跳过，全场子进程用例连坐）。
            runner_module.subprocess.Popen = orig_popen
        assert outcome.get("result") == "cancelled"
        lines = read_run_file(proot, "sb-y-456-a1")
        assert not any(
            l.get("type") == "stall-budget-terminated" for l in lines)

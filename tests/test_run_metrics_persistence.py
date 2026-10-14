"""
tests/test_run_metrics_persistence.py — fix-observability-gaps 1.3

验证 run 收尾（成功/失败分支）各产生一条含 duration_seconds 的结构化指标
（metric_type=run_metrics），含 usage 四分项、cost_usd、terminal、provider。

复用既有 Logger JSON 格式落盘设施，读日志文件 assert 结构化字段。
"""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import AgentRunner
from core.logger import Logger

# ── helpers ──────────────────────────────────────────────────────────────────

USAGE_WITH_COST = {
    "input_tokens": 120,
    "output_tokens": 80,
    "cache_creation_input_tokens": 10,
    "cache_read_input_tokens": 20,
    "cost_usd": 0.005,
    "unobserved": False,
}


def _make_runner_with_logger(tmp_path: Path, config: dict | None = None):
    """构造带真实 Logger 的最小 AgentRunner（可驱动 _execute_agent）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config or {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = tmp_path
    runner.logger = Logger(tmp_path / ".fenix" / "logs", "DEBUG")
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._provider_circuit._daily_reset_date = None
    runner._provider_circuit._daily_provider_attempts = {}
    runner._provider_circuit._daily_provider_warned = {}
    runner._provider_circuit.provider_circuits = {}
    runner.__dict__["_v2_server_instance"] = MagicMock()
    runner._v2_server._v2_inject_env.return_value = {}
    runner.__dict__["_token_accountant_instance"] = MagicMock()
    runner._build_prompt = lambda *a, **k: "test prompt"
    (tmp_path / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return runner


def _read_metric_lines(tmp_path: Path, terminal: str | None = None) -> list[dict]:
    """从 fenixd.log 读取所有 metric_type=run_metrics 行，可按 terminal 过滤。"""
    log_file = tmp_path / ".fenix" / "logs" / "fenixd.log"
    if not log_file.exists():
        return []
    results = []
    for raw in log_file.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        ctx = entry.get("context") or {}
        if ctx.get("metric_type") != "run_metrics":
            continue
        if terminal is not None and ctx.get("terminal") != terminal:
            continue
        results.append(ctx)
    return results


# ═════════════════════════════════════════════════════════════════════════════
# 成功分支：run 收尾产生含 duration_seconds + usage + cost_usd 的指标
# ═════════════════════════════════════════════════════════════════════════════

class TestRunMetricsSuccess:
    def test_success_run_produces_metric_with_duration(self, tmp_path):
        """成功 run → 日志含 metric_type=run_metrics, terminal=success, duration_seconds>0。"""
        runner = _make_runner_with_logger(tmp_path, {"agents": {"max_retries": 1}})
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            # evo-api-stall-signal-grading 1.3：返回 tuple 扩为 5 元（末位
            # 携带本 run latency 统计），本用例无样本上下文传零样本回退 dict。
            return ("output", 3, "sess-1", USAGE_WITH_COST,
                    {"rounds": 0, "stalls": 0, "max": None})

        runner._run_agent = fake_run_agent
        result = runner._execute_agent("spec-x", "verifier", "run-s1")
        runner.logger.close()

        assert result.success is True
        assert result.duration_seconds > 0
        metrics = _read_metric_lines(tmp_path, terminal="success")
        assert len(metrics) >= 1, "成功收尾应产生至少一条 run_metrics 日志"
        m = metrics[-1]
        assert m["run_id"] == "run-s1"
        assert m["spec"] == "spec-x"
        assert m["agent_type"] == "verifier"
        assert m["terminal"] == "success"
        assert isinstance(m["duration_seconds"], (int, float))
        assert m["duration_seconds"] > 0
        assert m["turns"] == 3
        assert m["input_tokens"] == 120
        assert m["output_tokens"] == 80
        assert m["cache_creation_input_tokens"] == 10
        assert m["cache_read_input_tokens"] == 20
        assert m["cost_usd"] == 0.005
        # verifier 无 provider 分配时 provider=None
        assert m["provider"] is None


# ═════════════════════════════════════════════════════════════════════════════
# 失败分支：重试耗尽后产生含 duration_seconds 的指标（terminal=failure）
# ═════════════════════════════════════════════════════════════════════════════

class TestRunMetricsFailure:
    def test_failure_run_produces_metric_with_duration(self, tmp_path, monkeypatch):
        """_run_agent 抛异常 + max_retries=1 → 重试耗尽终态，日志含 terminal=failure。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner_with_logger(tmp_path, {"agents": {"max_retries": 1}})
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None

        # 分类为非瞬断 → 不进入原地重试，直接跳出 attempt 循环
        runner.classify_transient_error = lambda *a, **k: False

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            exc = RuntimeError("claude CLI failed: Exit code: 1")
            exc.stderr_lines = ["error"]
            exc.exit_code = 1
            exc.has_result = False
            raise exc

        runner._run_agent = fake_run_agent
        result = runner._execute_agent("spec-x", "verifier", "run-f1")
        runner.logger.close()

        assert result.success is False
        assert result.duration_seconds > 0
        metrics = _read_metric_lines(tmp_path, terminal="failure")
        assert len(metrics) >= 1, "失败收尾应产生至少一条 terminal=failure run_metrics 日志"
        m = metrics[-1]
        assert m["run_id"] == "run-f1"
        assert m["spec"] == "spec-x"
        assert m["agent_type"] == "verifier"
        assert m["terminal"] == "failure"
        assert isinstance(m["duration_seconds"], (int, float))
        assert m["duration_seconds"] > 0
        # 失败路径 usage 未观测到 → input/output 为 0（extract_usage(None)）
        assert m["input_tokens"] == 0
        assert m["output_tokens"] == 0
        assert m["cost_usd"] is None


# ═════════════════════════════════════════════════════════════════════════════
# 使用既有 usage 信息（cost_usd 来自 gateway 返回，不伪造）
# ═════════════════════════════════════════════════════════════════════════════

class TestRunMetricsUsage:
    def test_metric_includes_usage_fields(self, tmp_path):
        """usage 四分项与 cost_usd 均原样落入指标（与 _extract_usage_info 对齐）。"""
        runner = _make_runner_with_logger(tmp_path, {"agents": {"max_retries": 1}})
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            return ("ok", 5, "sess-u", USAGE_WITH_COST,
                    {"rounds": 0, "stalls": 0, "max": None})

        runner._run_agent = fake_run_agent
        runner._execute_agent("spec-y", "verifier", "run-u1")
        runner.logger.close()

        metrics = _read_metric_lines(tmp_path, terminal="success")
        assert len(metrics) >= 1
        m = metrics[-1]
        assert m["run_id"] == "run-u1"
        assert m["input_tokens"] == USAGE_WITH_COST["input_tokens"]
        assert m["output_tokens"] == USAGE_WITH_COST["output_tokens"]
        assert m["cache_creation_input_tokens"] == USAGE_WITH_COST["cache_creation_input_tokens"]
        assert m["cache_read_input_tokens"] == USAGE_WITH_COST["cache_read_input_tokens"]
        assert m["cost_usd"] == USAGE_WITH_COST["cost_usd"]
        # duration_seconds 与 result.duration_seconds 一致
        assert m["duration_seconds"] > 0


# ═════════════════════════════════════════════════════════════════════════════
# 1.5 消费点：dashboard 读侧优先消费结构化指标（替代 mtime 推算）
# ═════════════════════════════════════════════════════════════════════════════

class TestRunMetricsConsumer:
    def test_duration_read_from_logged_metric(self, tmp_path, monkeypatch):
        """run 产物 mtime 与指标 duration 不一致时，读侧取指标值（消费点验收）。"""
        from core.dashboard.data.runs import _run_meta_cached

        # 构造 run 产物：st_ts 内嵌时间戳，mtime 故意放得很大（mtime 推算会给大值）
        ts = int(time.time()) - 100
        run_id = f"impl-spec-x-{ts}"
        runs_dir = tmp_path / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        run_file = runs_dir / f"{run_id}-a1.jsonl"
        run_file.write_text(json.dumps(
            {"type": "result", "status": "success", "timestamp": "2026-09-17T00:00:00Z"}
        ) + "\n", encoding="utf-8")
        # 把 mtime 设为「1 小时前创建、现在才写」→ mtime 推算 duration 会很大
        import os as _os
        _os.utime(run_file, (time.time(), time.time()))

        # 日志写入一条结构化指标（duration=42s，真实耗时）
        logs_dir = tmp_path / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)
        logger = Logger(logs_dir, "DEBUG")
        runner = AgentRunner.__new__(AgentRunner)
        runner.logger = logger
        runner._log_run_metrics(
            run_id=run_id, spec_name="spec-x", agent_type="implementer",
            duration_seconds=42.0, turns=5, usage_info=USAGE_WITH_COST,
            terminal="success", provider="p1", model="m1",
        )
        logger.close()

        stat = run_file.stat()
        meta = _run_meta_cached(run_file, stat, time.time(),
                                project_root=tmp_path)
        # 消费点返回结构化指标中的 duration（42s），而非 mtime 推算值
        assert meta["duration_seconds"] == 42

    def test_fallback_to_mtime_when_no_metric(self, tmp_path):
        """无指标日志（旧日志/未触发）→ 回退 mtime 推算，不丢历史数据。"""
        from core.dashboard.data.runs import _run_meta_cached

        ts = int(time.time()) - 100
        run_id = f"impl-spec-x-{ts}"
        runs_dir = tmp_path / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        run_file = runs_dir / f"{run_id}-a1.jsonl"
        run_file.write_text(json.dumps(
            {"type": "result", "status": "success", "timestamp": "2026-09-17T00:00:00Z"}
        ) + "\n", encoding="utf-8")

        stat = run_file.stat()
        meta = _run_meta_cached(run_file, stat, time.time(),
                                project_root=tmp_path)
        # 无指标：duration 由 mtime - start_ts 推出（>0 即可，不为 None）
        assert isinstance(meta["duration_seconds"], int)
        assert meta["duration_seconds"] >= 0


# ═════════════════════════════════════════════════════════════════════════════
# harness 品牌（add-harness-brand-projection 2.1）：run_metrics 行 harness 键
# ═════════════════════════════════════════════════════════════════════════════

class TestRunMetricsHarness:
    """run_metrics 结构化行的 ``harness`` 键（品牌投影真相源，写侧形态）。

    契约（design Decision 2）：
    - 派发装配时把该 run 的 adapter.name 记入 run 自身上下文（_run_harness），
      收尾从登记取值写入；
    - MUST NOT 收尾读进程级 get_current_adapter()——并发 run 收尾串号；
    - adapter 未装配的提前终态路径（登记缺失）省略该键，读侧缺省 claude 兜底。
    """

    def test_dispatch_run_carries_harness(self, tmp_path):
        """经 _execute_agent 派发的 run → 指标行携带 harness（config 缺省解析 claude）。"""
        runner = _make_runner_with_logger(tmp_path, {"agents": {"max_retries": 1}})
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"
        runner.worktree_manager.cleanup.return_value = None

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            return ("output", 1, "sess-1", USAGE_WITH_COST,
                    {"rounds": 0, "stalls": 0, "max": None})

        runner._run_agent = fake_run_agent
        result = runner._execute_agent("spec-x", "verifier", "run-h1")
        runner.logger.close()

        assert result.success is True
        metrics = _read_metric_lines(tmp_path, terminal="success")
        assert metrics, "成功收尾应产生 run_metrics 行"
        assert metrics[-1]["harness"] == "claude"
        # 派发登记随 run 终态外口摘除（_execute_agent finally），不残留
        assert "run-h1" not in getattr(runner, "_run_harness", {})

    def test_unregistered_run_omits_harness_key(self, tmp_path):
        """adapter 未装配的提前终态路径（无登记）→ 指标行省略 harness 键。"""
        logs_dir = tmp_path / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)
        logger = Logger(logs_dir, "DEBUG")
        runner = AgentRunner.__new__(AgentRunner)
        runner.logger = logger
        runner._log_run_metrics(
            run_id="run-early-cancel", spec_name="spec-x", agent_type="planner-standard",
            duration_seconds=0.0, turns=0, usage_info={},
            terminal="cancelled", provider=None, model=None,
        )
        logger.close()

        metrics = _read_metric_lines(tmp_path, terminal="cancelled")
        assert metrics, "取消终态也应产生 run_metrics 行"
        assert "harness" not in metrics[-1], (
            "未装配 adapter 的提前终态路径必须省略 harness 键（读侧缺省 claude 兜底）")

    def test_concurrent_runs_do_not_crosstalk_harness(self, tmp_path):
        """并发双 run 收尾各取自身登记：不串号（MUST NOT 读进程级全局）。"""
        logs_dir = tmp_path / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)
        logger = Logger(logs_dir, "DEBUG")
        runner = AgentRunner.__new__(AgentRunner)
        runner.logger = logger
        # 模拟两并发 run 各自的派发装配登记（一 claude 一 dsh）
        runner._run_harness = {"run-cla": "claude", "run-dsh": "dsh"}
        runner._log_run_metrics(
            run_id="run-cla", spec_name="spec-a", agent_type="implementer",
            duration_seconds=1.0, turns=1, usage_info={},
            terminal="success", provider=None,
        )
        runner._log_run_metrics(
            run_id="run-dsh", spec_name="spec-b", agent_type="implementer",
            duration_seconds=1.0, turns=1, usage_info={},
            terminal="success", provider=None,
        )
        logger.close()

        by_run = {m["run_id"]: m for m in _read_metric_lines(tmp_path)}
        assert by_run["run-cla"]["harness"] == "claude"
        assert by_run["run-dsh"]["harness"] == "dsh"

    def test_register_run_harness_repeat_is_noop(self):
        """同 run_id 重复登记为 no-op（dispatch 装配先行、spawn 装配 no-op 跟进）。"""
        runner = AgentRunner.__new__(AgentRunner)

        class _Adapter:
            name = "dsh"

        runner._register_run_harness("run-x", _Adapter())
        assert runner._run_harness == {"run-x": "dsh"}

        class _ClaudeAdapter:
            name = "claude"

        # 第二次登记（模拟 _run_agent spawn 装配）不覆盖 dispatch 值
        runner._register_run_harness("run-x", _ClaudeAdapter())
        assert runner._run_harness == {"run-x": "dsh"}

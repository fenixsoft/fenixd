"""
add-maintenance-lane-provider-failover：维护/判官范式车道 provider 候选环测试。

与 tests/test_provider_failover.py（dispatch attempt 环）互补，覆盖车道侧
单 run 候选环（runner._run_agent_with_chain_failover）与六条维护车道薄封装
（maintenance_runs._run_lane_agent_with_failover）。

按任务组织：
- TestChainFailoverLoop（2.1/2.3）：真候选环行为面——双候选 429（result 事件
  结构化）换候选成功（marker 真实链下标 + attempt + 300s 限流冷却）、链耗尽
  聚合异常保留结构化归因、全冷却廉价失败不启动进程、404 不换候选原样上抛、
  业务失败/超时不换候选、拒模型记账换候选、簿记缺失 fail-open、空链回退单发
  不写 marker、冷却跳过选择
- TestLaneWrapperFailOpen（2.2/R7）：桩 runner 缺候选环时薄封装的单发回退
  路径（链首直连、marker 0/1 口径、失败上下文挂载）
- TestLaneRegressions（3.6）：六条维护车道端到端——双候选链首候选 429 换
  第二候选成功、provider_marker 记录真实 chain_index/chain_len（含 attempt）、
  返回信封与既有降级路径结构不变
（判官范式共用性/镜像用例见 TestJudgeParadigmShared / TestJudgeLaneRegression，
2.4/3.7/3.8/3.9）
"""
import json
from pathlib import Path

import pytest

from core.agent_runner.maintenance_runs import (
    _run_lane_agent_with_failover,
    admin_disposition_path,
    run_administrator,
    run_arbiter,
    run_code_fix,
    run_code_review,
    run_evolution,
    run_self_review,
)
from core.agent_runner.provider_circuit import (
    PROVIDER_RATELIMIT_COOLDOWN_SECONDS,
    ProviderCircuit,
)
from core.agent_runner.runner import AgentRunner
from core.pm_engine.arbiter import arbiter_report_path
from core.self_review import REVIEW_OUT_PREFIX as _SELF_REVIEW_OUT_PREFIX

OK5 = ("ok", 1, "sess", {"input_tokens": 1, "output_tokens": 2},
       {"rounds": 1, "stalls": 0, "max": 0.0})

PROVIDERS = [
    {"name": "p1", "baseurl": "https://a.example", "apikey": "k1"},
    {"name": "p2", "baseurl": "https://b.example", "apikey": "k2"},
]


class FakeLogger:
    def __init__(self):
        self.records = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.records.append(("info", a[1] if len(a) > 1 else ""))

    def warning(self, *a, **k):
        self.records.append(("warning", a[1] if len(a) > 1 else ""))

    def error(self, *a, **k):
        self.records.append(("error", a[1] if len(a) > 1 else ""))

    def messages(self):
        return [m for _lvl, m in self.records]

    def has(self, text):
        return any(text in m for m in self.messages())


def make_real_runner(proot, config=None):
    """真 AgentRunner（绕 __init__，test_provider_failover.make_runner 同处方）：
    候选环与其簿记面（marker/冷却/拒模型记账）全走生产代码，仅 _run_agent
    由用例脚本化（实例属性遮蔽）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config or {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = Path(proot)
    runner.logger = FakeLogger()
    runner._running_agents = {}
    runner.__dict__["_provider_circuit_instance"] = ProviderCircuit(runner)
    pc = runner._provider_circuit
    pc._daily_reset_date = None
    pc._daily_provider_attempts = {}
    pc._daily_provider_warned = {}
    pc.provider_circuits = {}
    return runner


def dual_chain_config(roles, m1="m1", m2="m2"):
    """给指定角色配双候选链（对象元素形态，各候选独立 model——stub 按模型名
    脚本化成败）。"""
    models = {
        role: {"provider": [
            {"provider": "p1", "model": m1},
            {"provider": "p2", "model": m2},
        ]}
        for role in roles
    }
    return {"llm": {"providers": PROVIDERS}, "agents": {"models": models}}


def install_run_agent(runner, behavior):
    """实例级 _run_agent 替身：behavior(call, run_id, cwd) -> 5 元组或抛异常。
    返回 calls 列表供断言（调用面：模型/env/max_turns/spec/agent/run_id/cwd）。"""
    calls = []

    def _run_agent(prompt, cwd, run_id, model_override=None, env_overrides=None,
                   resume_session_id=None, max_turns=None, spec_name=None,
                   agent_type=None, task_progress_snapshot=None):
        call = {
            "model": model_override,
            "env": dict(env_overrides or {}),
            "max_turns": max_turns,
            "spec_name": spec_name,
            "agent_type": agent_type,
            "run_id": run_id,
            "cwd": cwd,
        }
        calls.append(call)
        return behavior(call, run_id, cwd)

    runner._run_agent = _run_agent
    return calls


def ratelimit_exc():
    """链首候选 429 的异常形态（findings F2）：降噪 error 仅 Exit code，
    429 证据在 result 事件结构化字段（api_error_status / result_text）。"""
    e = RuntimeError("claude CLI failed: Exit code: 1")
    e.api_error_status = 429
    e.result_text = (
        "API Error: Request rejected (429) · [1302]"
        "[您已达到每周/每月使用上限，您的限额将于稍后重置。]"
    )
    return e


def markers(proot, run_id):
    """读 run jsonl 的 provider_marker 行（含 attempt 键存在性断言用）。"""
    f = Path(proot) / ".fenix" / "runs" / f"{run_id}.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("type") == "provider_marker":
            out.append(rec)
    return out


# ═════════════════════════════════════════════════════════════════════════
# 2.1/2.3 候选环行为面
# ═════════════════════════════════════════════════════════════════════════


class TestChainFailoverLoop:
    """真候选环（真 AgentRunner + 真簿记，_run_agent 脚本化）。"""

    def _call(self, runner, tmp_path, run_id="lane-x", roles=("code-review",)):
        return _run_lane_agent_with_failover(
            runner,
            run_id=run_id,
            roles=list(roles),
            prompt="p",
            cwd=tmp_path,
            fallback_model="FALLBACK-M",
            spec_name=roles[0],
            agent_type=roles[0],
        )

    def test_dual_candidate_429_switches_to_second(self, tmp_path):
        """双候选链首 429（result 事件结构化）→ 换第二候选成功：7 元返回取
        最终候选、逐候选 env 组装、marker 真实链下标 + attempt、换候选日志、
        300s 限流冷却记账（R1/R2/R3/R5）。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))

        def behavior(call, run_id, cwd):
            if call["model"] == "m1":
                raise ratelimit_exc()
            return OK5

        calls = install_run_agent(runner, behavior)
        result = self._call(runner, tmp_path)

        assert len(result) == 7
        assert result[:5] == OK5
        assert result[5] == "p2" and result[6] == "m2"
        assert [c["model"] for c in calls] == ["m1", "m2"]
        # 逐候选 env：baseurl/model/CLAUDE_CONFIG_DIR 随候选切换（R1）
        assert calls[0]["env"]["ANTHROPIC_BASE_URL"] == "https://a.example"
        assert calls[1]["env"]["ANTHROPIC_BASE_URL"] == "https://b.example"
        assert calls[1]["env"]["ANTHROPIC_MODEL"] == "m2"
        assert "p2" in calls[1]["env"]["CLAUDE_CONFIG_DIR"]
        # marker：两条真实链下标 + additive attempt（R5）
        ms = markers(tmp_path, "lane-x")
        assert len(ms) == 2
        assert (ms[0]["provider"], ms[0]["model"]) == ("p1", "m1")
        assert (ms[0]["chain_index"], ms[0]["chain_len"], ms[0]["attempt"]) == (0, 2, 1)
        assert (ms[1]["provider"], ms[1]["chain_index"], ms[1]["attempt"]) == ("p2", 1, 2)
        # 换候选日志（R5）：车道 / 前候选 / 原因 / 后候选 / attempt 序号
        assert runner.logger.has("provider switched")
        assert runner.logger.has("原因=429")
        assert runner.logger.has("前候选=p1@m1")
        assert runner.logger.has("后候选=p2@m2（chain_index=1）")
        assert runner.logger.has("attempt 1/2")
        # 429 限流冷却：复用 switch 冷却通道 + 独立 300s 时长（R2，不改时长）
        # —— switch_cooldown_until 返回 monotonic 绝对到期时刻（与 _now 同钟）
        until = runner.switch_cooldown_until("p1")
        assert runner._now() + PROVIDER_RATELIMIT_COOLDOWN_SECONDS - 10 <= until <= runner._now() + PROVIDER_RATELIMIT_COOLDOWN_SECONDS + 10
        assert runner.switch_cooldown_until("p2") == 0.0

    def test_chain_exhausted_aggregates_last_error(self, tmp_path):
        """两候选全 429 → [model-chain-unavailable] 聚合异常：保留最后失败
        的结构化属性（429 终局重派归因依赖）、失败候选清单、归因取链尾。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))

        def behavior(call, run_id, cwd):
            raise ratelimit_exc()

        install_run_agent(runner, behavior)
        with pytest.raises(RuntimeError) as ei:
            self._call(runner, tmp_path)
        msg = str(ei.value)
        assert "[model-chain-unavailable]" in msg
        assert "2 个候选全部尝试失败" in msg
        exc = ei.value
        # 结构化属性拷贝（_FAILOVER_PRESERVED_EXC_ATTRS）
        assert exc.api_error_status == 429
        assert "429" in (exc.result_text or "")
        # 归因取数：最后尝试候选 + 链信息（D5/R6）
        assert exc.provider_name == "p2" and exc.model_override == "m2"
        assert exc.chain_len == 2
        assert exc.failed_candidates == [
            {"provider": "p1", "model": "m1", "chain_index": 0},
            {"provider": "p2", "model": "m2", "chain_index": 1},
        ]
        assert markers(tmp_path, "lane-x")[0]["attempt"] == 1

    def test_all_cooling_cheap_fail_no_process(self, tmp_path):
        """全链冷却 → 不调 _run_agent 直接 [model-chain-unavailable]（D6）。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))
        now = runner._now()
        runner._record_switch_cooldown("p1", now=now, cooldown_seconds=300)
        runner._record_switch_cooldown("p2", now=now, cooldown_seconds=300)
        calls = install_run_agent(runner, lambda call, run_id, cwd: OK5)
        with pytest.raises(RuntimeError) as ei:
            self._call(runner, tmp_path)
        assert calls == []
        assert "处于冷却/不可用（未启动进程）" in str(ei.value)

    def test_404_no_switch_reraised_with_context(self, tmp_path):
        """HTTP 404（4xx 配额/鉴权）→ 不换候选、异常原样上抛，additive 挂载
        最后候选上下文（R4）。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))

        def behavior(call, run_id, cwd):
            e = RuntimeError("claude CLI failed: Exit code: 1")
            e.api_error_status = 404
            e.result_text = "API Error: Request rejected (404)"
            raise e

        calls = install_run_agent(runner, behavior)
        with pytest.raises(RuntimeError) as ei:
            self._call(runner, tmp_path)
        assert ei.value.api_error_status == 404
        assert ei.value.provider_name == "p1"
        assert ei.value.model_override == "m1"
        assert ei.value.chain_index == 0 and ei.value.chain_len == 2
        assert [c["model"] for c in calls] == ["m1"]
        assert not runner.logger.has("provider switched")

    def test_business_failure_and_timeout_no_switch(self, tmp_path):
        """业务失败/超时（降噪 error 无切换签名 + 结构化 api_timeout）→
        不换候选原样上抛，避免把业务失败误当 provider 故障烧链（R4）。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))

        def behavior(call, run_id, cwd):
            e = RuntimeError("claude CLI failed: Exit code: 1")
            e.api_timeout = True
            raise e

        calls = install_run_agent(runner, behavior)
        with pytest.raises(RuntimeError) as ei:
            self._call(runner, tmp_path)
        assert ei.value.api_timeout is True
        assert ei.value.provider_name == "p1"
        assert [c["model"] for c in calls] == ["m1"]
        assert not runner.logger.has("provider switched")

    def test_unrecognized_model_switches_and_records(self, tmp_path):
        """拒模型（result 事件正文形态）→ 记账告警 + 换下一候选（R2/R3）。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))

        def behavior(call, run_id, cwd):
            if call["model"] == "m1":
                e = RuntimeError("claude CLI failed: Exit code: 1")
                e.result_text = (
                    "Model 'm1' is not recognized by this provider "
                    "[claude-code:unrecognized_model]"
                )
                raise e
            return OK5

        calls = install_run_agent(runner, behavior)
        result = self._call(runner, tmp_path)
        assert result[5] == "p2" and result[6] == "m2"
        assert [c["model"] for c in calls] == ["m1", "m2"]
        assert runner.logger.has("Unrecognized model rejected by provider")
        assert runner.logger.has("原因=unrecognized_model")

    def test_gateway_model_not_found_body_records_and_switches(self, tmp_path):
        """网关拒模型 HTTP 400 正文形态（「Model not found: <model>」仅在
        result 事件 result 字段、无 unrecognized_model 字样）→ 每候选记账
        WARNING + 换候选 + 双候选 switch 冷却 + 链尾 [model-chain-unavailable]
        归因（SPEC 场景「拒模型换候选并在链尾归因」；验证修复轮 BUG-01 回归：
        词表此前未覆盖该形态，链前进但无记账）。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))

        def behavior(call, run_id, cwd):
            e = RuntimeError("claude CLI failed: Exit code: 1")
            e.api_error_status = 400
            e.result_text = (
                f"Model not found: {call['model']} - this model does not exist"
            )
            raise e

        calls = install_run_agent(runner, behavior)
        with pytest.raises(RuntimeError) as ei:
            self._call(runner, tmp_path)
        msg = str(ei.value)
        assert "[model-chain-unavailable]" in msg
        assert "全链模型不可用" in msg
        assert [c["model"] for c in calls] == ["m1", "m2"]
        # 每候选各一条记账 WARNING（provider 名随候选区分，探针断言同款口径）
        warns = [m for lvl, m in runner.logger.records if lvl == "warning"]
        assert any(
            "Unrecognized model rejected" in m and "'p1'" in m for m in warns)
        assert any(
            "Unrecognized model rejected" in m and "'p2'" in m for m in warns)
        # 换候选成立且原因归拒模型（R5）
        assert runner.logger.has("provider switched")
        assert runner.logger.has("原因=unrecognized_model")
        # marker 真实链下标 + additive attempt（R5）
        ms = markers(tmp_path, "lane-x")
        assert [(m["chain_index"], m["chain_len"], m["attempt"]) for m in ms] == [
            (0, 2, 1), (1, 2, 2)]
        # 双候选均进 switch 冷却（拒模型非 429 → 默认 switch 时长通道）
        assert runner.switch_cooldown_until("p1") > runner._now()
        assert runner.switch_cooldown_until("p2") > runner._now()

    def test_bookkeeping_missing_failopen(self, tmp_path):
        """簿记方法缺失（实例属性置 None 遮蔽门面转发）→ 判定/换候选不受阻、
        marker 不写、无冷却记账，run 照常完成（R7 fail-open）。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))
        runner._record_switch_cooldown = None
        runner._write_provider_marker = None
        runner._record_unrecognized_model = None

        def behavior(call, run_id, cwd):
            if call["model"] == "m1":
                raise ratelimit_exc()
            return OK5

        calls = install_run_agent(runner, behavior)
        result = self._call(runner, tmp_path)
        assert result[5] == "p2"
        assert [c["model"] for c in calls] == ["m1", "m2"]
        assert markers(tmp_path, "lane-x") == []
        assert runner.switch_cooldown_until("p1") == 0.0

    def test_empty_chain_fallback_single_shot_no_marker(self, tmp_path):
        """未配置链 → 既有回退模型单次执行、不写 marker、7 元返回 provider
        维度为 None（R1/R7 与现状逐字段一致）。"""
        runner = make_real_runner(tmp_path, {})
        calls = install_run_agent(runner, lambda call, run_id, cwd: OK5)
        result = self._call(runner, tmp_path)
        assert len(result) == 7
        assert result[:5] == OK5
        assert result[5] is None and result[6] == "FALLBACK-M"
        assert [c["model"] for c in calls] == ["FALLBACK-M"]
        assert markers(tmp_path, "lane-x") == []

    def test_switch_cooldown_skip_selects_next(self, tmp_path):
        """链首处于限流冷却 → 选择跳过冷却候选直接执行第二候选（R1）。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))
        runner._record_switch_cooldown(
            "p1", now=runner._now(),
            cooldown_seconds=PROVIDER_RATELIMIT_COOLDOWN_SECONDS)
        calls = install_run_agent(runner, lambda call, run_id, cwd: OK5)
        result = self._call(runner, tmp_path)
        assert result[5] == "p2" and result[6] == "m2"
        assert [c["model"] for c in calls] == ["m2"]
        ms = markers(tmp_path, "lane-x")
        assert len(ms) == 1
        assert (ms[0]["provider"], ms[0]["chain_index"], ms[0]["chain_len"],
                ms[0]["attempt"]) == ("p2", 1, 2, 1)


# ═════════════════════════════════════════════════════════════════════════
# 2.2/R7 薄封装替身回退路径
# ═════════════════════════════════════════════════════════════════════════


class _StubRunnerNoLoop:
    """缺候选环的精简替身（车道单测同款 duck-typed 面）：薄封装应回退既有
    单发直连路径（R7 fail-open）。"""

    def __init__(self, proot, assignment):
        self.project_root = Path(proot)
        self.logger = FakeLogger()
        self._assignment = assignment
        self.calls = []
        self.marker_calls = []

    def _get_agent_model_assignment(self, role):
        return self._assignment

    def _get_admin_model(self):
        return "DEFAULT-M"

    def _ensure_agent_config_dir(self, provider_name, provider_model=""):
        d = self.project_root / ".fenix" / "agent-config" / provider_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_provider_marker(self, run_id, spec_name, agent_type,
                               provider_name, model, chain_index, chain_len,
                               attempt=None):
        self.marker_calls.append((provider_name, model, chain_index, chain_len))

    def _run_agent(self, prompt, cwd, run_id, model_override=None,
                   env_overrides=None, resume_session_id=None, max_turns=None,
                   spec_name=None, agent_type=None,
                   task_progress_snapshot=None):
        self.calls.append({
            "model": model_override, "env": dict(env_overrides or {}),
            "max_turns": max_turns, "spec_name": spec_name,
            "agent_type": agent_type,
        })
        return OK5


class TestLaneWrapperFailOpen:
    def test_stub_runner_without_loop_single_shot(self, tmp_path):
        """桩缺候选环 → 链首直连单发、marker 0/1 口径、7 元返回（R7）。"""
        assignment = [(PROVIDERS[0], "m1"), (PROVIDERS[1], "m2")]
        stub = _StubRunnerNoLoop(tmp_path, assignment)
        result = _run_lane_agent_with_failover(
            stub, run_id="stub-x", roles=["code-review"], prompt="p",
            cwd=tmp_path, fallback_model="DEFAULT-M",
            spec_name="code-review", agent_type="code-review")
        assert len(result) == 7
        assert result[:5] == OK5
        assert (result[5], result[6]) == ("p1", "m1")
        assert [c["model"] for c in stub.calls] == ["m1"]
        assert stub.calls[0]["env"]["ANTHROPIC_BASE_URL"] == "https://a.example"
        assert stub.marker_calls == [("p1", "m1", 0, 1)]

    def test_stub_runner_without_loop_failure_attaches_context(self, tmp_path):
        """桩单发失败 → 异常 additive 挂载归因上下文后原样上抛（R5/R7）。"""
        stub = _StubRunnerNoLoop(tmp_path, [(PROVIDERS[0], "m1")])

        def _boom(*a, **k):
            raise RuntimeError("gateway stall")

        stub._run_agent = _boom
        with pytest.raises(RuntimeError, match="gateway stall") as ei:
            _run_lane_agent_with_failover(
                stub, run_id="stub-x", roles=["code-review"], prompt="p",
                cwd=tmp_path, fallback_model="DEFAULT-M",
                spec_name="code-review", agent_type="code-review")
        assert ei.value.provider_name == "p1"
        assert ei.value.model_override == "m1"
        assert ei.value.chain_index == 0
        assert ei.value.chain_len == 1
        assert ei.value.failed_candidates == []


# ═════════════════════════════════════════════════════════════════════════
# 3.6 六条维护车道端到端回归
# ═════════════════════════════════════════════════════════════════════════

GOOD_REPORT = {
    "outcome": "resolved",
    "summary": "## 发生了什么\nx\n\n## 调查结论\ny\n\n## 为什么需要你决策\nz\n"
               "\n## 处置时间线\n1\n\n## 证据回链\nref",
    "root_cause": "root",
    "scene_snapshot": "snap",
    "forensic_timeline": [{"at": "t0", "event": "trigger"}],
    "actions_taken": ["清理坏产物"],
    "evidence_refs": [".fenix/runs/arbiter-x.jsonl"],
    "status_after": "ready",
}


class TestLaneRegressions:
    """六车道各自：双候选链首 429 → 换第二候选成功；marker 真实链下标（含
    attempt）；返回信封走既有收口（成功路径或既有降级信封，R7）。"""

    def _assert_switch_surface(self, runner, tmp_path, run_id, lane_agent,
                               marker_spec, marker_agent):
        """换候选公共断言：两次调用模型序、marker 两条真实链下标 + attempt、
        marker 的 spec/agent 字段按车道约定、换候选日志。"""
        calls = None  # 由用例自行断言调用面细节
        ms = markers(tmp_path, run_id)
        assert len(ms) == 2, f"{lane_agent} marker 数 {len(ms)}"
        assert (ms[0]["chain_index"], ms[0]["chain_len"], ms[0]["attempt"]) == (0, 2, 1)
        assert (ms[1]["chain_index"], ms[1]["chain_len"], ms[1]["attempt"]) == (1, 2, 2)
        assert ms[0]["spec"] == marker_spec and ms[0]["agent_type"] == marker_agent
        assert ms[1]["spec"] == marker_spec and ms[1]["agent_type"] == marker_agent
        assert runner.logger.has("provider switched")
        assert runner.logger.has("原因=429")
        assert runner.logger.has(f"agent_type={marker_agent}")

    def test_administrator_switches_and_succeeds(self, tmp_path):
        runner = make_real_runner(tmp_path, dual_chain_config(["administrator"]))

        def behavior(call, run_id, cwd):
            if call["model"] == "m1":
                raise ratelimit_exc()
            admin_disposition_path(Path(cwd), run_id).write_text(json.dumps({
                "spec": "spec-a",
                "problem": "卡死",
                "actions_taken": ["kill", "reset"],
                "result": "resolved",
                "escalate": False,
            }), encoding="utf-8")
            return ("output", 5, "sess",
                    {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
                    {"rounds": 5, "stalls": 0, "max": 0.5})

        calls = install_run_agent(runner, behavior)
        disp = run_administrator(runner, {
            "spec": "spec-a", "signal_type": "stuck", "description": "卡死"})
        assert disp.success is True
        assert disp.actions_taken == "kill\nreset"
        assert [c["model"] for c in calls] == ["m1", "m2"]
        # administrator 车道既有传参面保持：max_turns 显式 300 缺省、spec/agent 同名
        assert calls[1]["max_turns"] == 300
        assert calls[1]["spec_name"] == "spec-a"
        assert calls[1]["agent_type"] == "administrator"
        self._assert_switch_surface(runner, tmp_path, disp.run_id,
                                    "administrator", "spec-a", "administrator")

    def test_arbiter_switches_and_succeeds(self, tmp_path):
        runner = make_real_runner(tmp_path, dual_chain_config(["arbiter"]))

        def behavior(call, run_id, cwd):
            if call["model"] == "m1":
                raise ratelimit_exc()
            path = arbiter_report_path(runner.project_root, run_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(GOOD_REPORT, ensure_ascii=False),
                            encoding="utf-8")
            return ("", 1, None,
                    {"input_tokens": 100, "output_tokens": 50,
                     "cache_creation_input_tokens": 0,
                     "cache_read_input_tokens": 0},
                    None)

        calls = install_run_agent(runner, behavior)
        envelope = run_arbiter(runner, {
            "spec": "spec-a", "signal_type": "verify_env_blocked"})
        assert envelope["ok"] is True, envelope
        assert envelope["report"]["outcome"] == "resolved"
        assert [c["model"] for c in calls] == ["m1", "m2"]
        assert calls[1]["spec_name"] == "spec-a"
        assert calls[1]["agent_type"] == "arbiter"
        self._assert_switch_surface(runner, tmp_path, envelope["run_id"],
                                    "arbiter", "spec-a", "arbiter")

    def test_self_review_switches_and_succeeds(self, tmp_path):
        runner = make_real_runner(tmp_path,
                                  dual_chain_config(["self-review", "administrator"]))

        def behavior(call, run_id, cwd):
            if call["model"] == "m1":
                raise ratelimit_exc()
            out = Path(cwd) / ".fenix" / f"{_SELF_REVIEW_OUT_PREFIX}{run_id}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({
                "summary": "ok",
                "waste": ["无用等待"],
                "mistakes": [],
                "improvements": [],
            }, ensure_ascii=False), encoding="utf-8")
            return OK5

        calls = install_run_agent(runner, behavior)
        result = run_self_review(runner, "2026-11-10", "daily summary")
        assert result.success is True, result.error
        assert result.waste == ["无用等待"]
        assert [c["model"] for c in calls] == ["m1", "m2"]
        # _run_agent 的 agent_type 形参保持不传（超时覆盖查询面不扩面）、
        # marker 仍写车道名（self-review 先例）
        assert calls[1]["agent_type"] is None
        assert calls[1]["spec_name"] == "self-review"
        self._assert_switch_surface(runner, tmp_path, result.run_id,
                                    "self-review", "self-review", "self-review")

    def test_evolution_switches_and_falls_to_artifact_gate(self, tmp_path):
        """evolution：换候选成功执行后产物缺失 → 既有「产物文件未写出」降级
        信封（R7 返回结构不变），换候选/marker 面照常。"""
        runner = make_real_runner(tmp_path,
                                  dual_chain_config(["self-review", "administrator"]))

        def behavior(call, run_id, cwd):
            if call["model"] == "m1":
                raise ratelimit_exc()
            return OK5

        calls = install_run_agent(runner, behavior)
        result = run_evolution(runner, [], [])
        assert result.success is False
        assert "产物文件未写出" in result.error
        assert [c["model"] for c in calls] == ["m1", "m2"]
        # 每候选 post_provider_env：等待上限归零键两次都在（D7 顺序不变量）
        for c in calls:
            assert c["env"]["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "0"
        assert calls[1]["agent_type"] is None
        self._assert_switch_surface(runner, tmp_path, result.run_id,
                                    "evolution", "evolution", "evolution")

    def test_code_review_switches_and_falls_to_artifact_gate(self, tmp_path):
        """code-review：换候选成功执行后产物门拦截 → 既有失败信封（插入计数
        0、fail_face 在场），换候选/marker 面照常（R5/R7）。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))

        def behavior(call, run_id, cwd):
            if call["model"] == "m1":
                raise ratelimit_exc()
            return OK5

        calls = install_run_agent(runner, behavior)
        result = run_code_review(runner, ["src/a.py"], "scheduled")
        assert result.success is False
        assert result.inserted == 0 and result.updated == 0
        assert result.error  # 产物硬门归因在场
        assert result.fail_face is not None
        assert result.ratelimit_redispatch is None  # 非 429 失败不登记重派
        assert [c["model"] for c in calls] == ["m1", "m2"]
        assert calls[1]["max_turns"] is None
        self._assert_switch_surface(runner, tmp_path, result.run_id,
                                    "code-review", "code-review", "code-review")

    def test_code_fix_switches_and_succeeds(self, tmp_path):
        runner = make_real_runner(tmp_path,
                                  dual_chain_config(["code-fix", "code-review"]))
        wt = tmp_path / "wt"
        wt.mkdir()

        def behavior(call, run_id, cwd):
            if call["model"] == "m1":
                raise ratelimit_exc()
            out = Path(cwd) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"item_id": "abc123def456",
                                       "status": "fixed"},
                                      ensure_ascii=False) + "\n",
                           encoding="utf-8")
            return OK5

        calls = install_run_agent(runner, behavior)
        result = run_code_fix(runner, wt,
                              [{"item_id": "abc123def456", "path": "a.py"}],
                              run_id="code-fix-test-1")
        assert result.success is True, result.error
        assert [c["model"] for c in calls] == ["m1", "m2"]
        # marker 仍写 spec_name="code-review-fix" / agent_type="code-fix"
        # （车道既有 marker 约定不变），cwd 为 worktree
        assert calls[1]["cwd"] == wt
        assert calls[1]["max_turns"] is None
        self._assert_switch_surface(runner, tmp_path, "code-fix-test-1",
                                    "code-fix", "code-review-fix", "code-fix")


# ═════════════════════════════════════════════════════════════════════════
# 2.4/3.7/3.8/3.9 判官范式车道（spec-review / dispute-judge 镜像）
# ═════════════════════════════════════════════════════════════════════════

from core.agent_runner.runner import DEFAULT_GATEWAY_MODEL  # noqa: E402


class TestJudgeParadigmShared:
    """2.4：两判官车道共用同一候选环；未配置链走默认网关单次不写 marker。"""

    def test_both_judge_lanes_route_through_chain_loop(self, tmp_path):
        """run_spec_review 与 run_dispute_judge 均经 _run_agent_with_chain_failover
        （monkeypatch 计数/入参），provider_used/model_used 取环返回的最终候选。"""
        runner = make_real_runner(
            tmp_path, dual_chain_config(["spec-review", "dispute-judge"]))
        loop_calls = []
        real_loop = AgentRunner._run_agent_with_chain_failover

        def shim(**kw):
            loop_calls.append(kw)
            return "out", 1, "sess", {}, None, "p1", "m1"

        runner._run_agent_with_chain_failover = shim
        r1 = runner.run_spec_review("spec-a", run_id="spec-review-x")
        r2 = runner.run_dispute_judge(
            "spec-a", {"missing": ["a"]}, run_id="dispute-judge-x")
        assert len(loop_calls) == 2
        by_lane = {c["agent_type"]: c for c in loop_calls}
        assert set(by_lane) == {"spec-review", "dispute-judge"}
        for lane, call in by_lane.items():
            assert call["spec_name"] == "spec-a"
            assert call["fallback_model"] == DEFAULT_GATEWAY_MODEL
            # 完整链解析后传入（镜像同步：两处同一入参形态）
            assert [p["name"] for p, _m in call["assignment"]] == ["p1", "p2"]
        # 终态 provider 维度取环返回候选（R5）
        assert r1.success and r1.provider_used == "p1" and r1.model_used == "m1"
        assert r2.success and r2.provider_used == "p1" and r2.model_used == "m1"

    def test_unconfigured_chain_falls_back_default_gateway_no_marker(self, tmp_path):
        """未配置 agents.models → 两处均走 DEFAULT_GATEWAY_MODEL 单次执行、
        不写 provider_marker（与现状逐字段一致，R1/R7）。"""
        for lane_fn, args in (
            (AgentRunner.run_spec_review, ("spec-a",)),
            (AgentRunner.run_dispute_judge, ("spec-a", {"missing": []})),
        ):
            sub = tmp_path / f"proj-{lane_fn.__name__}"
            sub.mkdir()
            runner = make_real_runner(sub, {})
            calls = install_run_agent(runner, lambda call, run_id, cwd: OK5)
            result = lane_fn(runner, *args)
            assert result.success, result.error
            assert result.provider_used is None
            assert result.model_used == DEFAULT_GATEWAY_MODEL
            assert [c["model"] for c in calls] == [DEFAULT_GATEWAY_MODEL]
            run_id = result.run_id
            assert markers(sub, run_id) == []


class TestJudgeLaneRegression:
    """3.9：判官车道各自「双候选链首 429 → 换第二候选成功 + marker 真实链下标
    + provider_used 为最终候选」，镜像契约两处同步生效。"""

    @staticmethod
    def _loop_case(tmp_path, lane):
        runner = make_real_runner(tmp_path, dual_chain_config([lane]))

        def behavior(call, run_id, cwd):
            if call["model"] == "m1":
                raise ratelimit_exc()
            return ("", 1, "sess",
                    {"input_tokens": 10, "output_tokens": 5}, None)

        calls = install_run_agent(runner, behavior)
        return runner, calls

    def _assert_judge_switch(self, runner, tmp_path, run_id, lane):
        ms = markers(tmp_path, run_id)
        assert len(ms) == 2
        assert [(m["chain_index"], m["chain_len"], m["attempt"]) for m in ms] == [
            (0, 2, 1), (1, 2, 2)]
        for m in ms:
            assert m["agent_type"] == lane
        assert runner.logger.has("provider switched")
        assert runner.logger.has("原因=429")

    def test_spec_review_429_switches_second_candidate(self, tmp_path):
        runner, calls = self._loop_case(tmp_path, "spec-review")
        result = runner.run_spec_review("spec-a", run_id="spec-review-x")
        assert result.success, result.error
        assert result.provider_used == "p2" and result.model_used == "m2"
        assert [c["model"] for c in calls] == ["m1", "m2"]
        self._assert_judge_switch(runner, tmp_path, "spec-review-x", "spec-review")
        # marker spec 字段 = _run_agent 的 spec_name（车道 spec 名）
        assert markers(tmp_path, "spec-review-x")[0]["spec"] == "spec-a"

    def test_dispute_judge_429_switches_second_candidate(self, tmp_path):
        runner, calls = self._loop_case(tmp_path, "dispute-judge")
        result = runner.run_dispute_judge(
            "spec-a", {"missing": ["a"]}, run_id="dispute-judge-x")
        assert result.success, result.error
        assert result.provider_used == "p2" and result.model_used == "m2"
        assert [c["model"] for c in calls] == ["m1", "m2"]
        self._assert_judge_switch(runner, tmp_path, "dispute-judge-x", "dispute-judge")
        assert markers(tmp_path, "dispute-judge-x")[0]["spec"] == "spec-a"

    def test_judge_chain_exhausted_provider_used_is_last_candidate(self, tmp_path):
        """两判官链耗尽 → catch-all 归因回填最后尝试候选（镜像同步）。"""
        for lane, lane_fn, args in (
            ("spec-review", AgentRunner.run_spec_review, ("spec-a",)),
            ("dispute-judge", AgentRunner.run_dispute_judge,
             ("spec-a", {"missing": []})),
        ):
            sub = tmp_path / f"proj-{lane}"
            sub.mkdir()
            runner = make_real_runner(sub, dual_chain_config([lane]))
            install_run_agent(
                runner, lambda call, run_id, cwd: (_ for _ in ()).throw(ratelimit_exc()))
            result = lane_fn(runner, *args)
            assert result.success is False
            assert "[model-chain-unavailable]" in result.error
            assert result.provider_used == "p2" and result.model_used == "m2"


# ═════════════════════════════════════════════════════════════════════════
# 4.1/4.2 429 终局重派按链解析
# ═════════════════════════════════════════════════════════════════════════


class TestRatelimitRedispatchChain:
    """重派意图携带链信息（chain_len/失败候选）；复跑经候选环按当时冷却
    重新解析链、跳过仍在冷却的首候选（R6 MUST NOT 固定复用首跑链首）。"""

    def test_redispatch_intent_carries_chain_info(self, tmp_path):
        """链耗尽 429 → 意图 dict 与 run jsonl 标注行均携带 chain_len 与
        失败候选，归因 provider 取最后尝试候选。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))
        install_run_agent(
            runner, lambda call, run_id, cwd: (_ for _ in ()).throw(ratelimit_exc()))
        result = run_code_review(runner, ["src/a.py"], "scheduled")
        intent = result.ratelimit_redispatch
        assert intent is not None
        assert intent["provider"] == "p2"
        assert intent["chain_len"] == 2
        assert intent["failed_candidates"] == [
            {"provider": "p1", "model": "m1", "chain_index": 0},
            {"provider": "p2", "model": "m2", "chain_index": 1},
        ]
        f = tmp_path / ".fenix" / "runs" / f"{result.run_id}.jsonl"
        lines = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        ev = [x for x in lines if x.get("type") == "ratelimit_redispatch"]
        assert len(ev) == 1
        assert ev[0]["chain_len"] == 2
        assert len(ev[0]["failed_candidates"]) == 2
        assert runner.logger.has("chain_len=2")

    def test_redispatch_reparse_skips_cooled_first_candidate(self, tmp_path):
        """首轮全链 429（意图登记 + 双候选冷却）→ 复跑模拟「第二候选冷却已
        到期、首候选仍在窗口」→ 重新解析链跳过首候选，实际使用第二候选。"""
        runner = make_real_runner(tmp_path, dual_chain_config(["code-review"]))
        install_run_agent(
            runner, lambda call, run_id, cwd: (_ for _ in ()).throw(ratelimit_exc()))
        first = run_code_review(runner, ["src/a.py"], "scheduled")
        assert first.ratelimit_redispatch is not None
        assert runner.switch_cooldown_until("p1") > runner._now()
        assert runner.switch_cooldown_until("p2") > runner._now()
        # 模拟冷却到期推进：仅清第二候选（首候选保持冷却窗口内）
        runner._circuit_state("p2")["switch_cooldown_until"] = runner._now() - 1
        calls = install_run_agent(runner, lambda call, run_id, cwd: OK5)
        second = run_code_review(runner, ["src/a.py"], "scheduled",
                                 redispatch_of=first.run_id)
        assert second.ratelimit_redispatch is None, "成功调用不得再登记重派意图"
        assert [c["model"] for c in calls] == ["m2"], "复跑 MUST 跳过冷却中链首"

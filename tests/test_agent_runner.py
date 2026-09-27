"""agent_runner 关闭语义（SIGTERM terminate 流程）测试。

对应 spec/changes/fix-graceful-shutdown-agents 的 tasks 1.1-1.3、3.1，
覆盖 spec agent-shutdown-interrupt：关机时不逐 agent 等待、写 interrupted 标记、
缓冲窗口 SIGKILL 兜底、多 agent 并行终止。
"""

import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.agent_runner import (
    AGENT_TERMINATE_GRACE_SECONDS,
    AgentRunner,
    append_run_line,
)
from core.agent_runner.runner import admin_disposition_path
from tests.helpers import FakeLogger


def make_runner(proot: Path) -> AgentRunner:
    """构造最小 AgentRunner 实例（不触发真实 __init__）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._running_agents = {}
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


class TestTerminalHarvest:
    """verify-process-lifecycle 终态收割（_execute_agent try/finally）测试。

    覆盖 spec 场景：frozen 早退/异常路径/日限 raise 等任意终态后无注册条目
    残留；fast-track keep 不误收割；重复收割幂等。
    """

    def _runner_with_harvest(self, proot: Path):
        runner = make_runner(proot)
        # _v2_server 为只读 property（惰性 _v2_server_instance），注入 mock 用 __dict__
        runner.__dict__["_v2_server_instance"] = MagicMock()
        runner.worktree_manager = MagicMock()
        return runner

    def test_exception_path_harvests_registry(self, tmp_path):
        """_execute_agent 内部抛未预期异常 → finally 收割仍执行，注册条目清空。"""
        runner = self._runner_with_harvest(tmp_path / "proj")
        wt = Path("/w/impl-exc-1")

        def fake_inner(spec_name, agent_type, run_id, pre_wt_path=None,
                       conflict_summary=None, used_wts=None, handed_off=None):
            used_wts.add(wt)
            raise RuntimeError("unexpected boom")

        runner._execute_agent_inner = fake_inner
        with pytest.raises(RuntimeError):
            runner._execute_agent("spec", "implementer", "impl-exc-1")
        runner._v2_server._v2_stop_for_worktree.assert_called_once_with(wt)
        runner.worktree_manager.kill_strays.assert_called_once_with(
            wt.name)

    @pytest.mark.parametrize(
        "agent_type,run_id,worktree_kept",
        [
            pytest.param("fast-track", "impl-ft-1", False, id="fast-track-keep"),
            pytest.param("repair", "repair-1", True, id="repair-keep"),
        ],
    )
    def test_keep_branch_not_harvested(self, tmp_path, agent_type, run_id,
                                       worktree_kept):
        """keep 分支（fast-track hand-off / repair 载体）：终态收割不回收（dispatch 层负责）。"""
        runner = self._runner_with_harvest(tmp_path / "proj")
        wt = Path(f"/w/{run_id}")

        def fake_inner(spec_name, agent_type_, run_id_, pre_wt_path=None,
                       conflict_summary=None, used_wts=None, handed_off=None):
            used_wts.add(wt)
            handed_off.add(wt)  # 成功延迟清理 → 交接 dispatch 层
            result = SimpleNamespace(success=True, worktree_path=wt)
            if worktree_kept:
                result.worktree_kept = True
            return result

        runner._execute_agent_inner = fake_inner
        if agent_type == "repair":
            runner._execute_agent("spec", agent_type, run_id,
                                  pre_wt_path=wt, conflict_summary={})
        else:
            runner._execute_agent("spec", agent_type, run_id)
        runner._v2_server._v2_stop_for_worktree.assert_not_called()
        runner.worktree_manager.kill_strays.assert_not_called()

    def test_repeated_harvest_idempotent(self, tmp_path):
        """同一 worktree 收割两次（runner 层 + dispatch 层）→ 第二次无害。"""
        runner = self._runner_with_harvest(tmp_path / "proj")
        wt = Path("/w/impl-dup-1")
        runner._v2_harvest_used_worktrees({wt}, set())
        # 双调无害：不抛异常，注册表幂等弹出
        runner._v2_harvest_used_worktrees({wt}, set())
        assert runner._v2_server._v2_stop_for_worktree.call_count == 2

    @pytest.mark.parametrize(
        "agent_type,run_id,inner_result",
        [
            pytest.param("implementer", "impl-norm-1", SimpleNamespace(success=True),
                         id="normal-terminal"),
            pytest.param("verifier", "verify-frozen-1",
                         SimpleNamespace(success=False, error="spec frozen"),
                         id="frozen-early-exit"),
        ],
    )
    def test_terminal_harvests_used(self, tmp_path, agent_type, run_id,
                                    inner_result):
        """常规终态（成功 / frozen 早退等非 keep 终态）：收割对 used_wts 生效。"""
        runner = self._runner_with_harvest(tmp_path / "proj")
        wt = Path(f"/w/{run_id}")

        def fake_inner(spec_name, agent_type_, run_id_, pre_wt_path=None,
                       conflict_summary=None, used_wts=None, handed_off=None):
            used_wts.add(wt)
            return inner_result

        runner._execute_agent_inner = fake_inner
        runner._execute_agent("spec", agent_type, run_id)
        runner._v2_server._v2_stop_for_worktree.assert_called_once_with(wt)


class TestWaitForRunningAgents:
    def test_running_agent_terminated_and_marked(self, tmp_path):
        """在跑 agent 收到 SIGTERM 并退出，run 文件写入 interrupted 标记。"""
        proot = tmp_path / "proj"
        runs_dir = proot / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        runner = make_runner(proot)
        run_id = "impl-spec-a-1"
        proc = spawn_sleep(30)
        runner._running_agents[run_id] = proc

        # 短缓冲窗口，避免真实等待
        t0 = time.time()
        runner.wait_for_running_agents(timeout=1)
        elapsed = time.time() - t0

        # 进程已终止
        assert proc.poll() is not None
        # 总时长 ≪ 原 300s 串行等待（缓冲窗口级别）
        assert elapsed < 5
        # run 文件含 interrupted 标记
        lines = read_run_file(proot, run_id)
        assert any(e.get("type") == "interrupted" for e in lines)
        # 标记内容符合规范
        marker = next(e for e in lines if e.get("type") == "interrupted")
        assert marker["reason"] == "daemon shutdown"
        assert marker["by"] == "agent_runner"
        # 杀光后不再在在跑表
        assert run_id not in runner._running_agents

    def test_completed_agent_not_marked(self, tmp_path):
        """已 finalize 的完成 agent（不在 _running_agents）不写 interrupted 标记。"""
        proot = tmp_path / "proj"
        runs_dir = proot / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        runner = make_runner(proot)
        run_id = "impl-spec-done-1"
        # 完成 run 已写入正常 result 终态
        append_run_line(runs_dir / f"{run_id}.jsonl",
                        {"type": "result", "result": "完成", "num_turns": 3})

        runner.wait_for_running_agents(timeout=0)

        # 完成 run 不应多出 interrupted 标记
        lines = read_run_file(proot, run_id)
        assert not any(e.get("type") == "interrupted" for e in lines)
        assert lines[-1].get("type") == "result"

    def test_stuck_agent_sigkilled_after_grace(self, tmp_path):
        """缓冲窗口内未退出的 agent 被 SIGKILL。"""
        proot = tmp_path / "proj"
        runs_dir = proot / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        runner = make_runner(proot)
        run_id = "impl-spec-stuck-1"
        # 忽略 SIGTERM 的进程：收到 SIGTERM 也不退出
        proc = subprocess.Popen(
            ["python3", "-c",
             "import signal, time\n"
             "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
             "time.sleep(30)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        runner._running_agents[run_id] = proc

        t0 = time.time()
        runner.wait_for_running_agents(timeout=1)
        elapsed = time.time() - t0

        # SIGTERM 被忽略，但 SIGKILL 兜底强制终止
        assert proc.poll() is not None
        assert elapsed < 5
        # 标记已写入，不依赖 agent 优雅退出
        lines = read_run_file(proot, run_id)
        assert any(e.get("type") == "interrupted" for e in lines)

    def test_multiple_agents_terminated_in_parallel(self, tmp_path):
        """多 agent 并行终止，总时长与单 agent 一致（不随数量线性增长）。"""
        proot = tmp_path / "proj"
        runs_dir = proot / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        runner = make_runner(proot)
        ids = []
        for i in range(3):
            rid = f"impl-spec-{i}-1"
            ids.append(rid)
            runner._running_agents[rid] = spawn_sleep(30)

        t0 = time.time()
        runner.wait_for_running_agents(timeout=1)
        elapsed = time.time() - t0

        # 3 个 agent 同时收口，总时长仍 ≲ 缓冲窗口（非 3 倍）
        assert elapsed < 5
        for rid in ids:
            assert runner._running_agents.get(rid) is None or runner._running_agents[rid].poll() is not None
            lines = read_run_file(proot, rid)
            assert any(e.get("type") == "interrupted" for e in lines)

    def test_no_running_agents_is_noop(self, tmp_path):
        """无在跑 agent 时调用安全返回，不报错、不写标记。"""
        proot = tmp_path / "proj"
        runner = make_runner(proot)
        # 不应抛异常
        runner.wait_for_running_agents(timeout=0)
        assert runner._running_agents == {}

    def test_grace_constant_default(self):
        """AGENT_TERMINATE_GRACE_SECONDS 默认 10s，供 fenixd 优雅退出使用。"""
        assert AGENT_TERMINATE_GRACE_SECONDS == 10


class TestVerifierCheckpointResume:
    """verifier-checkpoint-resume：构造提示词时读取 verify-progress 断点（spec
    verifier-checkpoint-resume 3.1 / 3.2）。"""

    def test_prompt_includes_breakpoint_when_done_gt_0(self, tmp_path):
        """存在 done>0 的进度文件时，verifier 提示词含断点信息并从 done+1 继续。"""
        proot = tmp_path / "proj"
        vprog = proot / ".fenix" / "verify-progress"
        vprog.mkdir(parents=True, exist_ok=True)
        (vprog / "myspec.json").write_text(
            json.dumps({"total": 32, "done": 5, "current": "场景5: 计算器"}),
            encoding="utf-8",
        )
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("myspec", "verifier")
        assert "RESUME CHECKPOINT" in prompt
        assert "total=32" in prompt
        assert "done=5" in prompt
        assert "32" in prompt  # 任务总数保持
        # 从 done+1 开始
        assert "从第 6 个场景开始" in prompt
        # 首次写入保留断点起点
        assert "done=5（不要重置为 0）" in prompt

    @pytest.mark.parametrize(
        "progress_payload",
        [
            pytest.param(None, id="no-progress-file"),
            pytest.param({"total": 32, "done": 0, "current": "初始化"}, id="done-zero"),
            pytest.param({"done": 5}, id="missing-total-field"),
        ],
    )
    def test_prompt_fresh_start_without_breakpoint(self, tmp_path, progress_payload):
        """进度文件缺失 / done==0 / 缺 total 字段时均视作全新开始，不注入断点。"""
        proot = tmp_path / "proj"
        if progress_payload is not None:
            vprog = proot / ".fenix" / "verify-progress"
            vprog.mkdir(parents=True, exist_ok=True)
            (vprog / "myspec.json").write_text(
                json.dumps(progress_payload), encoding="utf-8",
            )
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("myspec", "verifier")
        assert "RESUME CHECKPOINT" not in prompt

    def test_corrupt_progress_removed_and_fresh_start(self, tmp_path):
        """进度文件 JSON 损坏时安全降级：移除以免污染后续 attempt，提示词全新开始。"""
        proot = tmp_path / "proj"
        vprog = proot / ".fenix" / "verify-progress"
        vprog.mkdir(parents=True, exist_ok=True)
        bad = vprog / "myspec.json"
        bad.write_text("{not valid json,,,", encoding="utf-8")
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("myspec", "verifier")
        assert "RESUME CHECKPOINT" not in prompt
        # 损坏文件已被移除
        assert not bad.exists()


class TestVerifierReportJson:
    """降级路径 verifier 提示词要求产出结构化 report.json（Dashboard 场景/缺陷数据源）。

    背景：新验证流程（planner-plan → verify_engine）失败降级到旧版 verifier 时不产
    report.json，导致 spec 详情页场景结果与 bug 列表恒为空（add-spec-list-hover-hint
    实证）。修复：提示词强制按 verify_engine 兼容结构写 report.json。
    """

    def test_prompt_requires_report_json(self, tmp_path):
        proot = tmp_path / "proj"
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt("myspec", "verifier")
        # 报告写入主树 verify-progress/<spec>/report.json（dashboard 读取位置）
        assert str(proot / ".fenix" / "verify-progress" / "myspec" / "report.json") in prompt
        # 结构关键字（verify_engine 兼容：scenario_id/status/assertion_results/screenshots）
        assert '"scenario_id"' in prompt
        assert '"assertion_results"' in prompt
        assert '"screenshots"' in prompt
        # status 判定规则（parse_bugs 依赖 fail/error 场景产出缺陷）
        assert "fail=断言/步骤失败(产品缺陷)" in prompt
        # 步骤 9 清理保留清单包含 report.json（防止 agent 自我清理误删）
        keep_line = [l for l in prompt.split("\n") if "保留：verification-report.md、" in l]
        assert keep_line
        assert "report.json" in keep_line[0]


class TestManualInterventionPrompt:
    """手动唤起 Admin 的固定指令必须进入 administrator prompt（2.3）。

    设计 D3：manual-intervention 信号复用现有 administrator 分支，无需新增
    prompt 分支；这里断言该分支把 signal 的 spec / description 渲染进 prompt。
    """

    def test_manual_intervention_renders_in_prompt(self, tmp_path):
        proot = tmp_path / "proj"
        runner = make_runner(proot)
        signal = {
            "signal_type": "manual-intervention",
            "spec": "stuck-spec",
            "severity": "major",
            "description": "人工呼叫：检查 SPEC stuck-spec 出现什么问题并尝试处置",
        }
        prompt = runner._prompt_builder._build_prompt("stuck-spec", "administrator", detail=signal)
        # 困境信号块包含目标 spec 与固定检查指令描述
        assert "- spec: stuck-spec" in prompt
        assert "- 类型: manual-intervention" in prompt
        assert "检查 SPEC stuck-spec 出现什么问题并尝试处置" in prompt
        # 仍是 Administrator 完整铁律提示（不破坏既有分支）
        assert "Fenix Administrator Agent" in prompt
        assert "先只读诊断" in prompt

    def test_manual_intervention_missing_spec_falls_back(self, tmp_path):
        """signal 缺 spec 时回退到 spec_name 参数。"""
        proot = tmp_path / "proj"
        runner = make_runner(proot)
        signal = {"signal_type": "manual-intervention", "description": "人工呼叫"}
        prompt = runner._prompt_builder._build_prompt("fallback-spec", "administrator", detail=signal)
        assert "- spec: fallback-spec" in prompt


# ── orphaned-state-probe-calibration：admin 处置失败证据 ──────


def _make_admin_runner_stub(proot: Path, fake_run_claude=None) -> AgentRunner:
    """run_administrator 测试共用的最小 AgentRunner 替身（绕过真实 __init__）。

    与 tests/test_admin.py 的 make_admin_runner_stub 同构：project_root/logger/
    _get_config/_get_admin_model/_get_agent_model_assignment/_prompt_builder.
    _build_prompt 链齐备；额外提供 _provider_circuit（MagicMock）——失败路径
    的 _record_signal_kill_or_label 对非信号死法调用 reset_signal_kill。
    """
    runner = AgentRunner.__new__(AgentRunner)
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._get_config = lambda key, default=None: default
    runner._get_admin_model = lambda: "claude-sonnet-5"
    runner._get_agent_model_assignment = lambda agent_type: None
    runner._prompt_builder._build_prompt = lambda *a, **k: "prompt"
    # _provider_circuit 是惰性属性（缓存 _provider_circuit_instance）；失败路径
    # 的 _record_signal_kill_or_label 对非信号死法调用 reset_signal_kill，
    # 直接注入缓存实例避免构造真实 ProviderCircuit。
    runner._provider_circuit_instance = MagicMock()
    if fake_run_claude is not None:
        runner._run_claude = fake_run_claude
    return runner


class TestRunAdministratorFailureEvidence:
    """run_administrator 非零退出的失败证据（orphaned-state-probe-calibration 1.5/2.5）。

    四项证据（原始 stderr 摘录 / 退出码 / provider·model / 带时间戳事件时间线）
    进 AdminDisposition.failure_evidence 独立字段；error 归因文本仍为降噪后形态
    （原始 stderr 不回填，error-attribution-denoise D5 语义不变）。
    """

    def test_failure_evidence_assembled_error_denoised(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)

        def failing_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                               max_turns, spec_name=None, agent_type=None):
            # 模拟真实失败 run 的产物：provider_marker 先行落盘、转录事件
            # 带时间戳、stderr 原始行、终态 error 行（均无 timestamp）。
            run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
            lines = [
                {"type": "provider_marker", "spec": "spec-a",
                 "agent_type": "administrator", "provider": "volc",
                 "model": "deepseek-v4-flash", "chain_index": 0, "chain_len": 1},
                {"type": "system", "subtype": "init",
                 "timestamp": "2026-09-15T09:30:12+00:00"},
                {"type": "assistant",
                 "timestamp": "2026-09-15T09:30:20+00:00", "message": {}},
                {"type": "user",
                 "timestamp": "2026-09-15T09:30:25+00:00", "message": {}},
                {"type": "stderr",
                 "line": "[claude-code:unrecognized_model] {\"model\":\"deepseek-v4.1-flash\"}"},
                {"type": "error", "error": "Exit code: 1", "exit_code": 1},
            ]
            run_file.write_text(
                "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines),
                encoding="utf-8")
            exc = RuntimeError("claude CLI failed: Exit code: 1")
            # _run_claude 失败路径携带原始信号（runner.py:2983-2985）
            exc.stderr_lines = [
                "[claude-code:unrecognized_model] {\"model\":\"deepseek-v4.1-flash\"}",
                "unrelated raw stderr line",
            ]
            exc.exit_code = 1
            raise exc

        runner = _make_admin_runner_stub(proot, fake_run_claude=failing_run_claude)
        disp = runner.run_administrator(
            {"spec": "spec-a", "signal_type": "stuck", "description": "卡死"})

        assert disp.success is False
        # error 归因文本仍为降噪后形态：原始 stderr 不回填
        assert "unrecognized_model" not in disp.error
        assert "Exit code: 1" in disp.error
        # 退出码
        assert disp.failure_evidence["exit_code"] == 1
        # 原始 stderr 摘录（独立证据字段，含被降噪丢弃的 [claude-code: 行）
        assert "unrecognized_model" in disp.failure_evidence["stderr_tail"]
        assert "unrelated raw stderr line" in disp.failure_evidence["stderr_tail"]
        # provider/model（run 产物 provider_marker 事件）
        assert disp.failure_evidence["provider_model"]["provider"] == "volc"
        assert disp.failure_evidence["provider_model"]["model"] == "deepseek-v4-flash"
        # 带时间戳事件时间线：末 3 条、全部跳过无 timestamp 事件
        ts = disp.failure_evidence["recent_event_timestamps"]
        assert len(ts) == 3
        assert ts[-1] == "2026-09-15T09:30:25+00:00"
        assert all("2026-09-15T09:30" in t for t in ts)

    def test_failure_evidence_absent_on_success(self, tmp_path):
        """成功路径 failure_evidence 为空 dict（不携带失败证据）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)

        def ok_run_claude(prompt, cwd, run_id, model_override, env_overrides,
                          max_turns, spec_name=None, agent_type=None):
            admin_disposition_path(cwd, run_id).write_text(
                json.dumps({"result": "resolved"}), encoding="utf-8")
            return "output", 5, "sess", {"input_tokens": 0, "output_tokens": 0,
                                         "cost_usd": 0.0}

        runner = _make_admin_runner_stub(proot, fake_run_claude=ok_run_claude)
        disp = runner.run_administrator({"spec": "spec-a", "signal_type": "stuck"})
        assert disp.success is True
        assert disp.failure_evidence == {}

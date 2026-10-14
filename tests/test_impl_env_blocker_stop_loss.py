"""evo-add-impl-env-blocker-stop-loss — 环境阻塞止损提示词 + 任务进度停滞观测 单测。

覆盖（tasks 1.1 / 1.2 / 2.1 / 2.2 / 3.1）：
- 提示词文本契约：agents/implementer.md 约束段四要素（连续 ≥3 次按尝试计数、
  design fallback 优先、无 fallback 登记 unfinished 转 partial、禁宿主内核级/
  镜像级改造）；agents/planner-plan.md 环境依赖标注与止损联动。失败尝试计数
  是提示词行为约定，框架侧无计数器交付项，不作框架行为测试（tasks 3.1 原文）。
- 2.2 ``ConfigLoader.get_task_stall_warn_config`` 归一化（缺省开启、非法回退、
  与 run_stall_budget_* 键互不干扰）。
- ``TaskCompletionWatcher`` 增量位点语义（跨块检测 / taskId 去重 / in_progress
  不计 / 半行持有 / 截断复位 / 损坏容错）。
- 2.1 装配级（仿 tests/test_impl_run_budget_sizing 装置：fake Popen + 节流
  stdout 驱动真实 ``_run_agent`` 轮询环，不启动真实 daemon/子进程）：停滞
  预警触发 WARNING、run_metrics ``task_stall`` 注记、观测不改变续期/击杀判定
  （无 turn_extension/timeout_extension 事件 + 判定输出逐位一致）、关闭态/
  非 impl 车道/无 TaskUpdate 能力三种静默形态。
- 既有预算 sizing 行为不回退（turn_budget_sizing / run_stall_budget 缺省形态
  与 ``_turn_limit_action`` evidence 不变）。
"""

import io
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.agent_runner.harness import (
    ClaudeAdapter,
    get_current_adapter,
    set_current_adapter,
)
from core.agent_runner.runner import AgentRunner
from core.config import ConfigLoader
from core.run_task_track import TaskCompletionWatcher
from tests.helpers import make_runner

REPO_ROOT = Path(__file__).resolve().parents[1]

# 提示词文本契约的载入单点（模块级一次，避免 class-scoped fixture 弃用形态）
_IMPLEMENTER_TEXT = (REPO_ROOT / "agents" / "implementer.md").read_text(
    encoding="utf-8")
_PLANNER_TEXT = (REPO_ROOT / "agents" / "planner-plan.md").read_text(
    encoding="utf-8")


@pytest.fixture(autouse=True)
def _claude_current_adapter():
    """用例期间把进程级当前 adapter 钉为 claude，结束后忠实还原。

    ``_run_agent`` 的 spawn 面读的是进程级全局 ``get_current_adapter()``
    （daemon 派发装配点按 agent.harness 写入；机器级 harness=dsh 的进程里
    它是 DshAdapter，本文件用例不传 model_override，dsh spawn 契约对缺模型
    fail-fast 抛 DshSpawnConfigError）——直接驱动真实 ``_run_agent`` 轮询环
    的用例因此顺序性依赖测试进程外的装配状态。钉 claude 使装置自足
    （惯例同 tests/test_harness_adapter.py 的 _restore_current_adapter）；
    save/restore 而非复位 None，不冲掉宿主进程的 ambient 装配。
    """
    prev_adapter = get_current_adapter()
    set_current_adapter(ClaudeAdapter())
    yield
    set_current_adapter(prev_adapter)


# ── 共用小装置（自足，不跨测试文件 import） ───────────────────────────


class _RecordingLogger:
    """记录 warning 的静默 logger（停滞预警在场/次数断言）。"""

    def __init__(self):
        self.warnings: list = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        self.warnings.append(a)

    def error(self, *a, **k):
        pass

    def stall_texts(self) -> list:
        return [a[1] for a in self.warnings
                if len(a) > 1 and "任务进度停滞预警" in str(a[1])]


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _init_evt(tools: list) -> dict:
    return {"type": "system", "subtype": "init", "session_id": "sess-tst",
            "tools": tools, "timestamp": _iso()}


def _assistant(*tool_uses) -> dict:
    """assistant 事件（tool_use 形态与真实 stream-json 一致）。"""
    return {"type": "assistant", "timestamp": _iso(),
            "message": {"content": [
                {"type": "tool_use", "id": f"tu_{i}", "name": name,
                 "input": inp}
                for i, (name, inp) in enumerate(tool_uses)]}}


def _task_update(status: str, task_id: int = 1) -> dict:
    return _assistant(("TaskUpdate", {"taskId": task_id, "status": status}))


def _result_evt(num_turns: int) -> dict:
    return {"type": "result", "subtype": "success", "result": "ok",
            "num_turns": num_turns, "session_id": "sess-tst",
            "is_error": False}


class _Stream:
    """节流 stdout/stderr 替身：逐行按 real sleep 节奏产出（不受 runner 的
    time shim 影响——构造时捕获真实 sleep 引用）。"""

    def __init__(self, lines: list, delay: float, real_sleep):
        self._lines = list(lines)
        self._delay = delay
        self._sleep = real_sleep

    def readline(self) -> str:
        if not self._lines:
            return ""
        if self._delay:
            self._sleep(self._delay)
        return self._lines.pop(0)


class _ThrottledFakeProc:
    """Popen 替身：stdout 节流逐行产出；poll 前 N 次恒 None 后自然成功收工。"""

    def __init__(self, events: list, line_delay: float = 0.02,
                 poll_pass_after: int = 150):
        self._lines = [json.dumps(e, ensure_ascii=False) + "\n" for e in events]
        self._delay = line_delay
        self._poll_calls = 0
        self._poll_pass_after = poll_pass_after
        self.pid = 4242
        self.returncode = None
        self.stdin = io.StringIO()

    @property
    def stdout(self):
        return _Stream(self._lines, self._delay, time.sleep)

    @property
    def stderr(self):
        return _Stream([], 0.0, time.sleep)

    def poll(self):
        self._poll_calls += 1
        if self._poll_calls >= self._poll_pass_after:
            self.returncode = 0
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9


class _FastTime:
    """runner 模块级 time 替身：轮询环 sleep 钳到毫秒级（测试提速且确定性），
    其余 time.* 委托真实模块（reader 节流用自身捕获的真实 sleep，不受影响）。"""

    def __init__(self, real, cap: float = 0.01):
        self._real = real
        self._cap = cap

    def __getattr__(self, name):
        return getattr(self._real, name)

    def sleep(self, seconds):
        self._real.sleep(min(seconds, self._cap))


def _drive_run_agent(monkeypatch, tmp_path: Path, events: list, config: dict,
                      agent_type: str, poll_pass_after: int = 150,
                      line_delay: float = 0.02):
    """驱动真实 ``_run_agent`` 轮询环到自然收工，返回 (runner, run_id)。"""
    import core.agent_runner.runner as rmod

    run_id = f"impl-stall-demo-{int(time.time() * 1000)}-a1"
    proc = _ThrottledFakeProc(events, line_delay=line_delay,
                              poll_pass_after=poll_pass_after)
    ns = SimpleNamespace(
        Popen=lambda *a, **k: proc,
        PIPE=subprocess.PIPE,
        TimeoutExpired=subprocess.TimeoutExpired,
        SubprocessError=subprocess.SubprocessError,
        run=subprocess.run,
    )
    monkeypatch.setattr(rmod, "subprocess", ns)
    monkeypatch.setattr(rmod, "time", _FastTime(time))
    monkeypatch.setattr(AgentRunner, "_effective_run_timeout",
                        lambda self, agent_type=None: 3600, raising=False)
    monkeypatch.setattr(AgentRunner, "_cancel_is_requested",
                        lambda self, run_id: False, raising=False)
    monkeypatch.setattr(AgentRunner, "_normalize_run_id",
                        lambda self, run_id: run_id, raising=False)
    runner = make_runner(tmp_path, config)
    runner.logger = _RecordingLogger()
    # rc=0 + success result 事件 → 正常返回四元组（run 全程未被观测面打断）
    out = runner._run_agent(
        "prompt", tmp_path, run_id, spec_name="stall-demo",
        agent_type=agent_type)
    assert out[0] == "ok", "自然收工路径应正常返回 result 文本"
    return runner, run_id


def _run_file_lines(proot: Path, run_id: str) -> list:
    run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    return [json.loads(ln) for ln in
            run_file.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _metrics_line(lines: list) -> dict:
    metrics = [e for e in lines if e.get("type") == "run_metrics"]
    assert len(metrics) == 1, "应恰好一条 run_metrics 行"
    return metrics[0]


# ── 1.1 / 1.2 提示词文本契约 ──────────────────────────────────────────


class TestPromptStopLossContract:
    """implementer.md 止损四要素 + planner-plan.md 环境依赖标注（tasks 1.1/1.2）。"""

    def test_count_rule_by_attempts_not_signature(self):
        """要素一：同一环境依赖连续 ≥3 次失败尝试即冻结，按尝试次数计不按
        错误签名（potplayer 事件错误码 ENODEV→ENOSYS→ENODEV 一路变化）。"""
        assert "≥3 次失败尝试" in _IMPLEMENTER_TEXT
        assert "按**尝试次数**计数" in _IMPLEMENTER_TEXT
        assert "不按错误签名" in _IMPLEMENTER_TEXT

    def test_design_fallback_first(self):
        """要素二：冻结后 design 有 fallback 条款先走 fallback。"""
        assert "fallback 条款" in _IMPLEMENTER_TEXT
        assert "有 fallback 先走 fallback" in _IMPLEMENTER_TEXT

    def test_no_fallback_registers_unfinished_partial(self):
        """要素三：无 fallback 登记 unfinished 转 partial 继续其余任务。"""
        assert "`unfinished`" in _IMPLEMENTER_TEXT
        assert '"partial"' in _IMPLEMENTER_TEXT
        assert "继续完成其余任务" in _IMPLEMENTER_TEXT

    def test_host_kernel_image_change_forbidden(self):
        """要素四：禁为救单个验证场景做宿主内核级/镜像级不可逆改造。"""
        assert "内核级/镜像级不可逆改造" in _IMPLEMENTER_TEXT
        assert "救单个验证场景" in _IMPLEMENTER_TEXT
        assert "幂等的环境预置不受此限" in _IMPLEMENTER_TEXT

    def test_stop_loss_block_in_constraints_section(self):
        """止损块位于「约束」段（提示词正文必经路径），非文末孤段。"""
        constraints = _IMPLEMENTER_TEXT.split("## 约束", 1)[1]
        assert "环境阻塞止损" in constraints
        for needle in ("≥3 次失败尝试", "有 fallback 先走 fallback",
                       "内核级/镜像级不可逆改造"):
            assert needle in constraints

    def test_planner_marks_env_dependent_scenarios(self):
        """planner-plan.md：环境依赖场景标注「环境依赖」类别 + 有/无
        fallback 标注，并与 ≥3 次止损规则联动。"""
        assert "环境依赖" in _PLANNER_TEXT
        assert "有 fallback" in _PLANNER_TEXT and "无 fallback" in _PLANNER_TEXT
        assert "≥3 次失败尝试" in _PLANNER_TEXT
        assert "止损" in _PLANNER_TEXT


# ── 2.2 配置归一化 ────────────────────────────────────────────────────


class TestTaskStallWarnConfig:
    """``get_task_stall_warn_config`` 归一化（tasks 2.2）。"""

    def test_empty_config_returns_defaults(self):
        assert ConfigLoader.get_task_stall_warn_config({}) == {
            "enabled": True, "turns": 200}

    def test_none_config_returns_defaults(self):
        assert ConfigLoader.get_task_stall_warn_config(None) == {
            "enabled": True, "turns": 200}

    def test_valid_values_pass_through(self):
        cfg = {"agents": {"task_stall_warn_enabled": False,
                          "task_stall_warn_turns": 50}}
        assert ConfigLoader.get_task_stall_warn_config(cfg) == {
            "enabled": False, "turns": 50}

    def test_integral_float_coerced(self):
        cfg = {"agents": {"task_stall_warn_turns": 80.0}}
        assert ConfigLoader.get_task_stall_warn_config(cfg)["turns"] == 80

    @pytest.mark.parametrize("bad", [None, True, False, "x", 0, -5, 2.5,
                                     float("nan")])
    def test_invalid_turns_fallback(self, bad):
        cfg = {"agents": {"task_stall_warn_turns": bad}}
        assert ConfigLoader.get_task_stall_warn_config(cfg)["turns"] == 200

    @pytest.mark.parametrize("bad", [1, 0, "yes", None])
    def test_non_bool_enabled_falls_back_default_on(self, bad):
        cfg = {"agents": {"task_stall_warn_enabled": bad}}
        assert ConfigLoader.get_task_stall_warn_config(cfg)["enabled"] is True

    def test_explicit_off_respected(self):
        cfg = {"agents": {"task_stall_warn_enabled": False,
                          "task_stall_warn_turns": "bad"}}
        got = ConfigLoader.get_task_stall_warn_config(cfg)
        assert got["enabled"] is False
        assert got["turns"] == 200


# ── TaskCompletionWatcher 增量位点语义 ───────────────────────────────


class TestTaskCompletionWatcher:
    """run_task_track 流内解析单点的增量观测器（tasks 2.1 复用面）。"""

    def _write(self, path: Path, events: list) -> None:
        with path.open("a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def test_detects_completion_across_chunks(self, tmp_path):
        rf = tmp_path / "run.jsonl"
        w = TaskCompletionWatcher(rf)
        assert w.poll() == 0  # 文件不存在：容错返回 0
        self._write(rf, [_init_evt(["TaskUpdate"]), _task_update("in_progress")])
        assert w.poll() == 0  # in_progress 不计完成
        self._write(rf, [_task_update("completed")])
        assert w.poll() == 1
        assert w.completed_count == 1

    def test_recompleted_same_task_not_growing(self, tmp_path):
        """同一 taskId 重复 completed 不增长计数（重复勾完成不是新进展，
        不得把轮询环侧停滞锚点反复重置）。"""
        rf = tmp_path / "run.jsonl"
        w = TaskCompletionWatcher(rf)
        self._write(rf, [_task_update("completed")])
        assert w.poll() == 1
        self._write(rf, [_task_update("completed")])
        assert w.poll() == 1
        self._write(rf, [_task_update("completed", task_id=2)])
        assert w.poll() == 2

    def test_partial_line_held_back(self, tmp_path):
        """末行不完整（无换行符）持有待下次，不误解析半行 JSON。"""
        rf = tmp_path / "run.jsonl"
        w = TaskCompletionWatcher(rf)
        line = json.dumps(_task_update("completed"), ensure_ascii=False)
        with rf.open("a", encoding="utf-8") as f:
            f.write(line[: len(line) // 2])  # 半行
        assert w.poll() == 0
        with rf.open("a", encoding="utf-8") as f:
            f.write(line[len(line) // 2:] + "\n")  # 补全
        assert w.poll() == 1

    def test_truncation_resets_and_rescans(self, tmp_path):
        """文件被截断/替换（size < 位点）→ 复位重扫，位点不超前卡死。"""
        rf = tmp_path / "run.jsonl"
        w = TaskCompletionWatcher(rf)
        self._write(rf, [_task_update("completed")])
        assert w.poll() == 1
        rf.write_text(json.dumps(_task_update("completed")) + "\n",
                      encoding="utf-8")
        assert w.poll() == 1

    def test_non_numeric_task_id_ignored(self, tmp_path):
        rf = tmp_path / "run.jsonl"
        w = TaskCompletionWatcher(rf)
        self._write(rf, [_assistant(("TaskUpdate", {"taskId": "abc",
                                                    "status": "completed"}))])
        assert w.poll() == 0

    def test_corrupt_lines_tolerated(self, tmp_path):
        rf = tmp_path / "run.jsonl"
        w = TaskCompletionWatcher(rf)
        with rf.open("a", encoding="utf-8") as f:
            f.write("not-json\n{\"type\": \"assistant\", broken\n")
            f.write(json.dumps(_task_update("completed")) + "\n")
        assert w.poll() == 1


# ── 2.1 装配级：轮询环观测行为 ────────────────────────────────────────


def _burst_events(tools: list = ("TaskCreate", "TaskUpdate", "Read")) -> list:
    """节流事件流：init → 进行 → 完成 → 多轮无完成 assistant → result。

    完成是第 2 个 assistant 事件（turn 2）：阈值 2 时结构上排除「完成被
    观测前 turn_count 已达阈值」的早爆形态——评估超阈前的每次 observe 都
    先 poll，完成行一旦落盘必然先被消费（锚点重置），故恰一次预警。
    """
    events: list = [_init_evt(list(tools))]
    events.append(_task_update("in_progress"))
    events.append(_task_update("completed"))  # 唯一一次任务完成（turn 2）
    for i in range(9):
        events.append(_assistant(("Read", {"path": f"f{i}"})))
    events.append(_result_evt(num_turns=11))
    return events


class TestTaskStallObservationAssembly:
    """真实 ``_run_agent`` 轮询环的停滞观测行为（tasks 2.1）。"""

    def test_stall_warn_fires_and_metrics_annotated(self, monkeypatch, tmp_path):
        """超阈 → WARNING 恰一次（episode 内不刷屏）+ run_metrics task_stall
        注记（warned=True）+ run 自然收工不被观测面打断。"""
        runner, run_id = _drive_run_agent(
            monkeypatch, tmp_path, _burst_events(),
            {"agents": {"run_timeout_seconds": 3600,
                        "task_stall_warn_turns": 2}},
            agent_type="implementer")
        stall_warns = runner.logger.stall_texts()
        assert len(stall_warns) == 1, f"停滞预警应恰一次，实得 {len(stall_warns)}"
        assert "不参与续期/击杀判定" in stall_warns[0]
        lines = _run_file_lines(tmp_path, run_id)
        metrics = _metrics_line(lines)
        note = metrics["task_stall"]
        assert note["warned"] is True
        assert note["threshold"] == 2
        assert note["completed_tasks"] == 1
        assert note["stall_turns"] >= 2
        # 观测不参与续期/击杀判定：全程无续期/超时事件
        assert not [e for e in lines
                    if e.get("type") in ("turn_extension", "timeout_extension")]

    def test_disabled_config_silent(self, monkeypatch, tmp_path):
        """enabled=False：零观测（无 WARNING、task_stall=None）。"""
        runner, run_id = _drive_run_agent(
            monkeypatch, tmp_path, _burst_events(),
            {"agents": {"run_timeout_seconds": 3600,
                        "task_stall_warn_enabled": False,
                        "task_stall_warn_turns": 2}},
            agent_type="implementer", poll_pass_after=60)
        assert runner.logger.stall_texts() == []
        assert _metrics_line(_run_file_lines(tmp_path, run_id))["task_stall"] \
            is None

    def test_review_lane_silent(self, monkeypatch, tmp_path):
        """非 impl 车道（评审/裁决）：默认开启也不观测。"""
        runner, run_id = _drive_run_agent(
            monkeypatch, tmp_path, _burst_events(),
            {"agents": {"run_timeout_seconds": 3600,
                        "task_stall_warn_turns": 2}},
            agent_type="spec-review", poll_pass_after=60)
        assert runner.logger.stall_texts() == []
        assert _metrics_line(_run_file_lines(tmp_path, run_id))["task_stall"] \
            is None

    def test_no_task_update_capability_silent(self, monkeypatch, tmp_path):
        """harness 无 TaskUpdate 工具：「无完成」不是停滞证据，fail-open
        不观测（含 TaskUpdate 事件在场也不计）。"""
        events = _burst_events(tools=("Read", "Bash"))
        runner, run_id = _drive_run_agent(
            monkeypatch, tmp_path, events,
            {"agents": {"run_timeout_seconds": 3600,
                        "task_stall_warn_turns": 2}},
            agent_type="implementer", poll_pass_after=60)
        assert runner.logger.stall_texts() == []
        assert _metrics_line(_run_file_lines(tmp_path, run_id))["task_stall"] \
            is None


class TestObservationDecisionNeutrality:
    """观测不改变续期/击杀判定（tasks 2.1/3.1）。"""

    def test_turn_limit_action_bitwise_identical(self, tmp_path):
        """观测开启（小阈值）与关闭两配置下，同输入 ``_turn_limit_action``
        输出逐位一致（含 remaining_tasks evidence，既有行为不回退）。"""
        spec_dir = tmp_path / "spec" / "changes" / "demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "# demo\n- [ ] 1.1 a\n- [ ] 1.2 b\n- [x] 1.3 c\n",
            encoding="utf-8")
        run_file = tmp_path / ".fenix" / "runs" / "impl-demo-1-a1.jsonl"
        run_file.parent.mkdir(parents=True)
        run_file.write_text(json.dumps({
            "type": "user", "timestamp": _iso(),
            "message": {"content": [{"type": "tool_result",
                                     "tool_use_id": "tu_0",
                                     "content": "r"}]}}) + "\n",
            encoding="utf-8")
        kwargs = dict(spec_name="demo", run_id="impl-demo-1-a1",
                      turn_extensions_used=0, wt_path=None,
                      agent_type="implementer", max_turns=400)
        on = make_runner(tmp_path, {"agents": {
            "run_timeout_seconds": 3600, "task_stall_warn_turns": 2}}
        )._turn_limit_action(run_file, **kwargs)
        off = make_runner(tmp_path, {"agents": {
            "run_timeout_seconds": 3600, "task_stall_warn_enabled": False}}
        )._turn_limit_action(run_file, **kwargs)
        assert on == off
        assert on["action"] == "extend"
        assert "remaining_tasks=2" in on["evidence"]

    def test_stall_state_not_shared_across_runs(self, tmp_path):
        """观测态为 ``_run_agent`` 局部（每次调用重建），不落实例状态——
        跨 run/跨 attempt 不串数。"""
        from core.run_task_track import TaskCompletionWatcher
        rf = tmp_path / "run.jsonl"
        rf.write_text(json.dumps(_task_update("completed")) + "\n",
                      encoding="utf-8")
        st = {"watch": TaskCompletionWatcher(rf), "cap_ready": True,
              "cap_ok": True, "last_count": 0, "anchor_turn": 0,
              "warned": False}
        runner = make_runner(tmp_path, {"agents": {
            "run_timeout_seconds": 3600, "task_stall_warn_turns": 2}})
        runner.logger = _RecordingLogger()
        runner._task_stall_observe(st, {"turns": 2}, rf, "r1", turns=5)
        assert runner.logger.stall_texts() == []  # 刚完成重置锚点 → 不预警
        runner._task_stall_observe(st, {"turns": 2}, rf, "r1", turns=8)
        assert len(runner.logger.stall_texts()) == 1  # 超阈预警
        # 新 run 新建观测态：互不影响
        st2 = dict(st, watch=TaskCompletionWatcher(rf), warned=False,
                   last_count=0, anchor_turn=0)
        runner2 = make_runner(tmp_path, {"agents": {"run_timeout_seconds": 3600}})
        runner2.logger = _RecordingLogger()
        runner2._task_stall_observe(st2, {"turns": 2}, rf, "r2", turns=1)
        assert runner2.logger.stall_texts() == []


# ── 既有预算 sizing 行为不回退 ────────────────────────────────────────


class TestBudgetSizingNoRegress:
    """新增键不改变既有预算 sizing / 判停配置缺省形态（tasks 3.1）。"""

    def test_turn_budget_sizing_defaults_unchanged(self):
        from core.fast_track_result import get_turn_budget_sizing_config
        assert get_turn_budget_sizing_config({}) == {
            "enabled": True,
            "full_scale_threshold": 45,
            "suggested_turn_cap": 800,
            "bookkeeping_share_threshold": 0.5,
            "kill_early": {
                "enabled": False,
                "remaining_tasks_threshold": 10,
                "progress_floor": 0.1,
            },
        }

    def test_run_stall_budget_defaults_unchanged(self):
        """缺省关闭灰度语义不变：enabled=False / stalls=5 / window=600s。"""
        assert ConfigLoader.get_run_stall_budget_config({}) == {
            "enabled": False, "stalls": 5, "window_seconds": 600.0}

    def test_suggested_turn_cap_unchanged(self):
        """签名 (base_turn_cap, scale, cfg)：只抬不压、严格大于抬档。"""
        from core.fast_track_result import suggested_turn_cap_for_scale
        assert suggested_turn_cap_for_scale(100, 300, None) == 800  # 抬档
        assert suggested_turn_cap_for_scale(100, 2, None) == 100  # 小规模取 base
        assert suggested_turn_cap_for_scale(1000, 300, None) == 1000  # 不压 base

    def test_impl_turn_budget_assembly_unchanged(self, tmp_path):
        """装配级 sizing：大规模抬档 / 小规模维持 base / 评审车道不参与。"""
        spec_dir = tmp_path / "spec" / "changes" / "big"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "".join(f"- [ ] 1.{i} t{i}\n" for i in range(1, 51)),
            encoding="utf-8")
        runner = make_runner(tmp_path, {"agents": {
            "max_turns": 300, "run_timeout_seconds": 3600}})
        effective, snap = runner._impl_turn_budget("big", "implementer")
        assert effective == 800
        assert snap == {"checked_ids": frozenset(), "unchecked": 50}
        for lane in ("spec-review", "dispute-judge", None):
            eff, no_snap = runner._impl_turn_budget("big", lane)
            assert eff == 300
            assert no_snap is None

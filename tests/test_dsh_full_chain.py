"""tests/test_dsh_full_chain.py — add-dsh-adapter-integration 5.2 全链 spawn 测试。

「就绪后 agent.harness: dsh 全链 spawn dsh 进程、监督/终态收口按归一化事件
运转」：以**真实子进程**（stub ``dsh`` 可执行，非 Popen 替身）驱动
``runner._run_agent``——SpawnRequest → DshAdapter.build_spawn_spec → Popen →
读环投影 → 终态收口 → 返回值四元组 + run_metrics/projection/dump 旁路产物。

stub 经 ``DshAdapterConfig(dsh_bin=...)`` 注入（等价 PATH 解析；argv 形态
契约已由 tests/test_harness_dsh_adapter.py 快照锁定）。健康检查 fail-fast
「未装 dsh/版本不符无 run 被代跑」侧归 tests/test_harness_dsh_adapter.py
（check_health 单测）与 tests/test_harness_config.py（dispatch 门零副作用）。
"""

import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from core.agent_runner.harness import (
    DshAdapter,
    DshAdapterConfig,
    set_current_adapter,
)
from core.agent_runner.harness.dsh_adapter import (
    DSH_API_KEY_ENV,
    DSH_BUNDLE_MOUNT_MARKER,
    DSH_ROUTE_PROVIDER_NAME,
)

PROMPT = "实现 demo 任务并自检"

_HAPPY_EVENTS = [
    {"type": "session", "sessionId": "session-stub-fc1", "cwd": "/wt"},
    {"type": "text", "text": "开工"},
    {"type": "tool_call", "callId": "call_fc_1", "tool": "TaskCreate",
     "input": {"subject": "Task 1.1: full chain"}},
    {"type": "tool_result", "callId": "call_fc_1", "status": "completed",
     "result": "Task #1 created"},
    {"type": "status", "phase": "step_end", "turn": 1, "step": 1,
     "usage": {"inputTokens": 200, "outputTokens": 50, "totalTokens": 250}},
    {"type": "status", "phase": "turn_end", "turn": 1,
     "reason": {"kind": "completed"}},
    {"type": "final", "text": "全链完成", "reason": {"kind": "completed"}},
]

_NO_USAGE_EVENTS = [
    {"type": "session", "sessionId": "session-stub-fc3", "cwd": "/wt"},
    {"type": "text", "text": "无 usage 流"},
    {"type": "status", "phase": "turn_end", "turn": 1,
     "reason": {"kind": "completed"}},
    {"type": "final", "text": "完成但网关不报 usage", "reason": {"kind": "completed"}},
]

_ADOPT_DEAD_EVENTS = [
    {"type": "error",
     "message": 'dsh: SESSION_ADOPT: session "fenix-impl-dsh-rd-a1" '
                "does not exist; omit --session-id"},
]

_STUB_TEMPLATE = '''#!/usr/bin/env python3
import json, os, sys
raw_stdin = sys.stdin.read()
env_snapshot = {k: v for k, v in os.environ.items()
                if k in ("FENIX_DSH_PROVIDER_API_KEY", "ANTHROPIC_API_KEY",
                         "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
                         "CLAUDE_CONFIG_DIR", "DSH_HOME")}
with open(%(record)r, "w", encoding="utf-8") as f:
    json.dump({"argv": sys.argv[1:], "stdin": raw_stdin,
               "env": env_snapshot, "cwd": os.getcwd()}, f, ensure_ascii=False)
mode = open(%(mode)r).read().strip() if os.path.exists(%(mode)r) else "happy"
for line in open(%(events)r, encoding="utf-8").read().splitlines():
    if line.strip():
        sys.stdout.write(line + "\\n")
sys.stdout.flush()
if mode == "adopt_dead":
    sys.stderr.write('dsh: SESSION_ADOPT: session "fenix-impl-dsh-rd-a1" '
                     "does not exist; omit --session-id\\n")
    sys.stderr.flush()
    sys.exit(1)
sys.exit(0)
'''


class RecLogger:
    """记录型 logger（断言 run_metrics 结构化字段用）。"""

    def __init__(self):
        self.infos = []
        self.warnings = []

    def debug(self, *a, **k):
        pass

    def info(self, component, message, context=None):
        self.infos.append({"component": component, "message": message,
                           "context": context or {}})

    def warning(self, component, message, context=None):
        self.warnings.append({"component": component, "message": message})

    def error(self, component, message, context=None):
        pass


def _make_fixture(tmp_path: Path, events, mode="happy"):
    """stub dsh 可执行 + 事件/模式文件；返回（stub 路径, record 路径）。"""
    events_file = tmp_path / "stub-events.jsonl"
    events_file.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8")
    mode_file = tmp_path / "stub-mode"
    mode_file.write_text(mode, encoding="utf-8")
    record_file = tmp_path / "stub-record.json"
    stub = tmp_path / "dsh"
    stub.write_text(_STUB_TEMPLATE % {
        "record": str(record_file),
        "mode": str(mode_file),
        "events": str(events_file),
    }, encoding="utf-8")
    stub.chmod(0o755)
    return stub, record_file


def _make_runner(proot: Path, logger: RecLogger):
    from core.agent_runner import AgentRunner
    from tests.helpers import make_runner as _base
    runner = _base(proot, {"agents": {"run_timeout_seconds": 120}})
    runner.logger = logger
    return runner


def _run_file_entries(proot: Path, run_id: str):
    rf = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    return [json.loads(l) for l in
            rf.read_text(encoding="utf-8").splitlines() if l.strip()]


_ENV_OVERRIDES = {
    "ANTHROPIC_BASE_URL": "http://gw.example:9000",
    "ANTHROPIC_API_KEY": "sk-test-123",
    "ANTHROPIC_MODEL": "deepseek-v4-flash",
}


class TestDshFullChain:
    """真实子进程全链：spawn → 投影 → 终态收口 → 产物对账。"""

    def test_happy_path_spawn_projection_terminal(self, tmp_path):
        stub, record_file = _make_fixture(tmp_path, _HAPPY_EVENTS)
        proot = tmp_path / "proj"
        proot.mkdir()
        (proot / ".fenix").mkdir()
        logger = RecLogger()
        runner = _make_runner(proot, logger)
        prev = set_current_adapter(DshAdapter(DshAdapterConfig(dsh_bin=str(stub))))
        try:
            output, turns, session_id, usage = runner._run_agent(
                PROMPT, proot, "impl-dsh-fc-1",
                model_override="deepseek-v4-flash",
                env_overrides=dict(_ENV_OVERRIDES),
                spec_name="demo", agent_type="implementer")
        finally:
            set_current_adapter(prev)

        # 返回值四元组：result 文本 / turn_end 计数轮次 / init session_id /
        # usage 按 step_end 求和（不伪造成本）
        assert output == "全链完成"
        assert turns == 1
        assert session_id == "session-stub-fc1"
        assert usage["usage_source"] == "available"
        assert usage["input_tokens"] == 200
        assert usage["output_tokens"] == 50
        assert usage.get("cost_usd") in (None, 0.0)

        # spawn 契约端到端：argv / patch 渲染 / stdin 载荷 / env 防串扰桥接
        rec = json.loads(record_file.read_text(encoding="utf-8"))
        argv = rec["argv"]
        assert argv[argv.index("--profile") + 1] == "fenix"
        patch_path = argv[argv.index("--patch") + 1]
        import yaml
        patch = yaml.safe_load(Path(patch_path).read_text(encoding="utf-8"))
        assert patch[0]["id"] == DSH_BUNDLE_MOUNT_MARKER
        assert patch[0]["config"]["model"] == {
            "provider": DSH_ROUTE_PROVIDER_NAME,
            "baseURL": "http://gw.example:9000",
            "apiKeyEnv": DSH_API_KEY_ENV,
            "model": "deepseek-v4-flash",
        }
        # argv 契约（DSH_APP_NAME 注记）：--profile 即完成 app 选择，MUST NOT
        # 携带裸 "headless"（占任务 positional 槽位、stdin prompt 被忽略）。
        assert argv[argv.index("--patch") + 2:] == ["--json"]
        assert "--session-id" not in argv  # 全新会话不传（严格采纳语义）
        assert rec["stdin"] == PROMPT
        assert rec["env"]["FENIX_DSH_PROVIDER_API_KEY"] == "sk-test-123"
        for banned in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL",
                       "ANTHROPIC_MODEL", "CLAUDE_CONFIG_DIR"):
            assert banned not in rec["env"], banned

        # 归一化事件写盘：init 首行 / result 终行 / assistant+user 载体在场
        entries = _run_file_entries(proot, "impl-dsh-fc-1")
        types = [e["type"] for e in entries]
        assert types[0] == "system" and entries[0]["subtype"] == "init"
        assert entries[0]["harness"] == "dsh"
        assert types[-1] == "result"
        assert "assistant" in types and "user" in types
        result_line = entries[-1]
        assert result_line["result"] == "全链完成"
        assert result_line["session_id"] == "session-stub-fc1"

        # 可观测性三件套产物：dump 旁路（原始行）+ run_metrics 结构化日志
        dump = proot / ".fenix" / "runs" / "impl-dsh-fc-1.dsh-events.jsonl"
        assert dump.exists()
        raw = [l for l in dump.read_text(encoding="utf-8").splitlines()
               if l.strip()]
        assert json.loads(raw[0])["type"] == "session"
        assert len(raw) == len(_HAPPY_EVENTS)
        metrics = [c for c in (r["context"] for r in logger.infos)
                   if c.get("metric_type") == "run_metrics"]
        assert metrics, "run_metrics 结构化日志应落盘"
        proj = next((c["projection"] for c in metrics if "projection" in c),
                    None)
        assert proj and proj["harness"] == "dsh"
        assert proj["events_received"]["final"] == 1
        assert proj["events_ignored"]["status"] == 2

    def test_usage_unavailable_degrades_without_fabrication(self, tmp_path):
        """4.3：usage 不可得 → usage_source=unavailable 降级标记，数值不伪造。"""
        stub, _ = _make_fixture(tmp_path, _NO_USAGE_EVENTS)
        proot = tmp_path / "proj"
        proot.mkdir()
        (proot / ".fenix").mkdir()
        logger = RecLogger()
        runner = _make_runner(proot, logger)
        prev = set_current_adapter(DshAdapter(DshAdapterConfig(dsh_bin=str(stub))))
        try:
            _, _, _, usage = runner._run_agent(
                PROMPT, proot, "impl-dsh-fc-3",
                model_override="deepseek-v4-flash",
                env_overrides=dict(_ENV_OVERRIDES),
                spec_name="demo", agent_type="implementer")
        finally:
            set_current_adapter(prev)
        assert usage["usage_source"] == "unavailable"
        assert usage["input_tokens"] == 0 and usage["output_tokens"] == 0
        # 降级标记落 metrics：_log_run_metrics 按 usage_source 键追加结构化
        # 日志（inner 收尾驱动；此处直驱该方法锁定消费端行为）
        runner._log_run_metrics(
            run_id="impl-dsh-fc-3", spec_name="demo", agent_type="implementer",
            duration_seconds=0.0, turns=1, usage_info=dict(usage),
            terminal="success")
        src_metrics = [c for c in (r["context"] for r in logger.infos)
                       if c.get("usage_source") is not None]
        assert src_metrics and src_metrics[-1]["usage_source"] == "unavailable"

    def test_resume_adopt_dead_terminal_not_hanging(self, tmp_path):
        """4.1/5.2：--session-id 采纳失败 → 终态 error 行 + RuntimeError 及时
        上抛（不悬挂）；异常文本带采纳死 marker，attempt 环经
        is_resume_dead_error 判定后回退新 session 重跑并留痕。"""
        stub, record_file = _make_fixture(tmp_path, _ADOPT_DEAD_EVENTS,
                                          mode="adopt_dead")
        proot = tmp_path / "proj"
        proot.mkdir()
        (proot / ".fenix").mkdir()
        runner = _make_runner(proot, RecLogger())
        prev = set_current_adapter(DshAdapter(DshAdapterConfig(dsh_bin=str(stub))))
        try:
            with pytest.raises(RuntimeError) as cm:
                runner._run_agent(
                    PROMPT, proot, "impl-dsh-rd-a1",
                    model_override="deepseek-v4-flash",
                    env_overrides=dict(_ENV_OVERRIDES),
                    resume_session_id="fenix-impl-dsh-rd-a1",
                    spec_name="demo", agent_type="implementer")
        finally:
            set_current_adapter(prev)

        err = str(cm.value)
        assert "does not exist; omit --session-id" in err
        # attempt 环回退判别经 adapter duck-typing 成员命中（回退新 session
        # 的循环分支本体归 attempt 环集成面；此处锁定判别输入端到端成立）
        assert DshAdapter().is_resume_dead_error(err) is True
        # spawn 契约：resume 时 --session-id 紧随 --json 之后
        rec = json.loads(record_file.read_text(encoding="utf-8"))
        assert rec["argv"][rec["argv"].index("--json") + 1:] == [
            "--session-id", "fenix-impl-dsh-rd-a1"]
        # 终态收口：run 文件末行为可终判 error 行（liveness 可判定，无悬挂在飞）
        entries = _run_file_entries(proot, "impl-dsh-rd-a1")
        assert entries[-1]["type"] == "error"
        assert "dsh: SESSION_ADOPT" in entries[-1]["error"]

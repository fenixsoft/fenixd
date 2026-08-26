"""agent_runner 关闭语义（SIGTERM terminate 流程）测试。

对应 openspec/changes/fix-graceful-shutdown-agents 的 tasks 1.1-1.3、3.1，
覆盖 spec agent-shutdown-interrupt：关机时不逐 agent 等待、写 interrupted 标记、
缓冲窗口 SIGKILL 兜底、多 agent 并行终止。
"""

import json
import subprocess
import time
from pathlib import Path

import pytest

from core.agent_runner import (
    AGENT_TERMINATE_GRACE_SECONDS,
    AgentRunner,
    append_run_line,
)


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
        # 完成的 agent 已移除 _running_agents（shutdown 边界安全）
        assert run_id not in runner._running_agents

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

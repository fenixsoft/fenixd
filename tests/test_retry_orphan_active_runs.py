"""fix-retry-orphan-active-runs：原地重试弃置产物 superseded 终态 + 读侧 stale 兜底。

写侧：两处原地重试通道（provider 瞬断 / artifact-gate）在 transient_retry 落盘后
必须向同一文件补写 superseded 终态，重试写入新 -rN 文件，恢复「终态后置」不变量。
读侧：_RUN_TERMINAL_STATUS_MAP 认 superseded；末行非终态 + mtime 停更超阈值判 stale，
活跃计数只认 running/empty。

参照 tests/test_transient_backoff.py（_build_runner / _make_chain_config / _TransientError）
与 tests/test_agent_runner_gate.py（产物硬门路径）既有 fixture 惯例。
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.agent_runner import AgentRunner
from core.agent_runner.prompt_builder import planner_result_path
from tests.helpers import FakeLogger


def _make_runner(tmp_path: Path, config: dict | None = None) -> AgentRunner:
    """构造可驱动 _execute_agent 的最小 runner（test_transient_backoff 同款）。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = config or {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = tmp_path
    runner.logger = FakeLogger()
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


def _make_chain_config(agent_type: str = "planner-judge") -> dict:
    """含单 provider 候选链的 config（transient 预算长度 1，attempt 上限 2）。"""
    return {
        "llm": {"providers": [
            {"name": "inferaiapi.com", "baseurl": "https://a.com", "apikey": "k1"},
        ]},
        "agents": {
            "models": {
                agent_type: {
                    "provider": "inferaiapi.com",
                    "model": "deepseek-v4-flash",
                },
            },
            "max_retries": 2,
            "transient_backoff_schedule": "1",
        },
    }


def _usage_ok() -> dict:
    return {"input_tokens": 1, "output_tokens": 2,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0, "cost_usd": None}


def _read_tail(runs_dir: Path, run_id: str) -> list:
    """读取某 run jsonl 全部事件（缺失文件返回空列表）。"""
    p = runs_dir / f"{run_id}.jsonl"
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


class _TransientError(RuntimeError):
    """模拟 Claude CLI 瞬断失败异常（携带 stderr_lines / exit_code / has_result）。"""

    def __init__(self, msg="cli transient failure", *, stderr_lines=None,
                 exit_code=1, has_result=False):
        super().__init__(msg)
        self.stderr_lines = stderr_lines or []
        self.exit_code = exit_code
        self.has_result = has_result


# ═══════════════════════════════════════════════════════════════════════════
# 1.4 写侧：provider 瞬断通道
# ═══════════════════════════════════════════════════════════════════════════

class TestProviderTransientSuperseded:
    """provider 瞬断原地重试 → 旧文件末两行为 transient_retry + superseded。"""

    def _transient_stderr(self):
        return ["[claude-code:unrecognized_model] model deepseek-v4 not found"]

    def test_provider_transient_writes_superseded(self, tmp_path, monkeypatch):
        """每次原地重试换新文件前，旧产物文件补写 superseded 终态。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _make_chain_config("planner-judge"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"

        runs_dir = tmp_path / ".fenix" / "runs"

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            # 模拟真实 _run_agent 在流文件落盘普通事件（provoke 弃置场景）
            with (runs_dir / f"{run_id}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "assistant",
                                    "message": {"content": []}}) + "\n")
                f.flush()
            raise _TransientError(stderr_lines=self._transient_stderr(),
                                  exit_code=1, has_result=False)

        runner._run_agent = fake_run_agent
        result = runner._execute_agent("spec-x", "planner-judge", "run-t1")
        assert result.success is False

        # 旧产物文件 a1：瞬断重试发生后弃置，末两行为 transient_retry + superseded
        a1 = _read_tail(runs_dir, "run-t1-a1")
        assert a1, "a1 文件应有内容"
        self.assert_last_two(a1)
        # a1 末尾 superseded 携带 spec/provider/timestamp 字段
        sup = a1[-1]
        assert sup["type"] == "superseded"
        assert sup["spec"] == "spec-x"
        assert "provider" in sup and "timestamp" in sup
        # 重试写入新 -r1 文件（attempt 1 的第二次调用）
        r1 = _read_tail(runs_dir, "run-t1-a1-r1")
        assert r1, "重试应写入新 -r1 文件"
        # superseded 只作为弃置文件终态存在于 a1，不写入重试文件（旧文件不再被追加）
        assert all(e["type"] != "superseded" for e in r1)
        # a1 末行后无后续行——superseded 是该文件绝对末行
        self.assert_mtime_unchanged_consistent(a1, runs_dir, "run-t1-a1")

    @staticmethod
    def assert_last_two(events: list):
        assert events[-1]["type"] == "superseded"
        assert events[-2]["type"] == "transient_retry"

    @staticmethod
    def assert_mtime_unchanged_consistent(events, runs_dir, run_id):
        """superseded 是文件绝对末行（重试不再向旧文件追加）。"""
        p = runs_dir / f"{run_id}.jsonl"
        lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == len(events)
        assert json.loads(lines[-1])["type"] == "superseded"


# ═══════════════════════════════════════════════════════════════════════════
# 1.4 写侧：artifact-gate 通道
# ═══════════════════════════════════════════════════════════════════════════

class TestArtifactGateSuperseded:
    """artifact-gate 失败原地重试 → 旧文件末两行为 transient_retry + superseded。"""

    def test_artifact_gate_writes_superseded(self, tmp_path, monkeypatch):
        """产物硬门失败（exit 0 无产物）通道同样补写 superseded。"""
        monkeypatch.setattr(time, "sleep", lambda _: None)
        runner = _make_runner(tmp_path, _make_chain_config("planner-judge"))
        wt = tmp_path / "wt"
        wt.mkdir(parents=True)
        runner.worktree_manager = MagicMock()
        runner.worktree_manager.create.return_value = wt
        runner.worktree_manager.get_branch_name.return_value = "fenix/spec-x"

        runs_dir = tmp_path / ".fenix" / "runs"
        result_path = planner_result_path(tmp_path, "spec-x", "planner-judge")

        calls = {"n": 0}

        def fake_run_agent(prompt, cwd, run_id, model_override, env_overrides,
                            resume_session_id=None, max_turns=None,
                            spec_name=None, agent_type=None,
                            task_progress_snapshot=None):
            calls["n"] += 1
            with (runs_dir / f"{run_id}.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "assistant",
                                    "message": {"content": []}}) + "\n")
                f.flush()
            # exit 0 但不写产物 → 触发 AgentArtifactGateError 重试
            return ("done", 1, f"sess-{calls['n']}", _usage_ok())

        runner._run_agent = fake_run_agent
        result = runner._execute_agent("spec-x", "planner-judge", "run-g1")
        assert result.success is False
        assert "结果文件缺失" in (result.error or "")

        a1 = _read_tail(runs_dir, "run-g1-a1")
        assert a1, "a1 文件应有内容"
        # 末两行为 transient_retry（reason=artifact_gate）+ superseded
        assert a1[-1]["type"] == "superseded"
        assert a1[-2]["type"] == "transient_retry"
        assert a1[-2]["reason"] == "artifact_gate"
        # 重试写入新 -r1 文件
        r1 = _read_tail(runs_dir, "run-g1-a1-r1")
        assert r1, "重试应写入新 -r1 文件"
        assert all(e["type"] != "superseded" for e in r1)


# ═══════════════════════════════════════════════════════════════════════════
# 2.4 读侧：superseded 映射 + stale mtime 兜底
# ═══════════════════════════════════════════════════════════════════════════

def _write_run(runs_dir: Path, run_id: str, events: list) -> Path:
    p = runs_dir / f"{run_id}.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return p


def _set_mtime(p: Path, age_seconds: float):
    """用 os.utime 构造指定距今秒数的 mtime（勿 sleep 等真实时间）。"""
    t = time.time() - age_seconds
    os.utime(p, (t, t))
    return t


class TestReadSideSuperseded:
    """superseded 尾行判终态（classify_run 纯函数直测）。"""

    def test_superseded_last_line_terminal(self):
        from core.dashboard.data import classify_run
        status = classify_run([{"type": "assistant", "message": {"content": []}},
                               {"type": "superseded"}])
        assert status == "superseded"
        status2 = classify_run([{"type": "transient_retry"},
                                {"type": "superseded"}])
        assert status2 == "superseded"


class TestReadSideStale:
    """mtime 陈旧兜底：get_runs 判 stale + project_summary 不计入活跃。"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmpdir) / ".fenix" / "runs"
        self.runs_dir.mkdir(parents=True)
        # 最小 STATE.md（project_summary → parse_state 需要）
        (Path(self.tmpdir) / ".fenix" / "STATE.md").write_text(
            "# Fenix Project State\n\n## Specs\n\n### demo-spec\n- status: ready\n"
            "- priority: 1\n- created: 2026-01-01T00:00:00+00:00\n"
            "- updated: 2026-01-01T00:00:00+00:00\n- error: null\n- depends_on: null\n",
            encoding="utf-8")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _status(self, run_id: str) -> str:
        from core.dashboard.data import get_runs
        runs = {r["run_id"]: r for r in get_runs(self.tmpdir)}
        assert run_id in runs, f"run {run_id} 未列出: {runs.keys()}"
        return runs[run_id]["status"]

    def test_stale_nonterminal_old_mtime(self):
        """② 末行 transient_retry + mtime 陈旧(>1800s) → stale 且不计入活跃。"""
        ts = int(time.time())
        rid = f"impl-retry-orphan-{ts}-a1"
        p = _write_run(self.runs_dir, rid, [
            {"type": "assistant", "message": {"content": []}},
            {"type": "transient_retry", "backoff_seconds": 30}])
        _set_mtime(p, 40 * 3600)  # 40 小时 ≫ 1800s
        assert self._status(rid) == "stale"
        from core.dashboard.data import project_summary
        s = project_summary("p", self.tmpdir)
        assert s["active_runs"] == 0

    def test_fresh_transient_still_active(self):
        """③ 末行 transient_retry + mtime 新鲜(<1800s) → running 且计入活跃。"""
        ts = int(time.time())
        rid = f"impl-retry-orphan-{ts}-a1"
        p = _write_run(self.runs_dir, rid, [
            {"type": "assistant", "message": {"content": []}},
            {"type": "transient_retry", "backoff_seconds": 30}])
        _set_mtime(p, 120)  # 2 分钟（退避序列 30/60/120s 之内）
        assert self._status(rid) == "running"
        from core.dashboard.data import project_summary
        s = project_summary("p", self.tmpdir)
        assert s["active_runs"] == 1

    def test_empty_file_old_mtime_stale(self):
        """④ 空文件 + 陈旧 mtime → stale。"""
        ts = int(time.time())
        rid = f"impl-retry-orphan-{ts}-a1"
        p = self.runs_dir / f"{rid}.jsonl"
        p.write_text("", encoding="utf-8")
        _set_mtime(p, 7200)
        assert self._status(rid) == "stale"

    def test_result_terminal_mtime_ignored(self):
        """⑤ result 终态文件 + 任意 mtime → done 不受兜底影响。"""
        ts = int(time.time())
        rid = f"impl-retry-orphan-{ts}-a1"
        p = _write_run(self.runs_dir, rid, [
            {"type": "assistant", "message": {"content": []}},
            {"type": "result", "result": "完成"}])
        _set_mtime(p, 40 * 3600)
        assert self._status(rid) == "done"
        # 终态也不计入活跃
        from core.dashboard.data import project_summary
        s = project_summary("p", self.tmpdir)
        assert s["active_runs"] == 0

    def test_superseded_old_mtime_not_active(self):
        """① 末行 superseded → superseded 终态；陈旧文件不计入活跃。"""
        ts = int(time.time())
        rid = f"impl-retry-orphan-{ts}-a1"
        p = _write_run(self.runs_dir, rid, [
            {"type": "transient_retry", "backoff_seconds": 30},
            {"type": "superseded"}])
        _set_mtime(p, 40 * 3600)
        assert self._status(rid) == "superseded"
        from core.dashboard.data import project_summary
        s = project_summary("p", self.tmpdir)
        assert s["active_runs"] == 0

    def test_stale_excluded_from_active_by_type(self):
        """stale run 不进入 active_runs_by_type 分组。"""
        ts = int(time.time())
        rid = f"impl-retry-orphan-{ts}-a1"
        p = _write_run(self.runs_dir, rid, [
            {"type": "assistant", "message": {"content": []}},
            {"type": "transient_retry", "backoff_seconds": 30}])
        _set_mtime(p, 40 * 3600)
        from core.dashboard.data import project_summary
        s = project_summary("p", self.tmpdir)
        assert s["active_runs"] == 0
        assert "implementer" not in s["active_runs_by_type"]
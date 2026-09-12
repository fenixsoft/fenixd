"""add-turn-limit-anchor-c — 轮次上限活性感知续期 + 消耗观测口径 单测。

覆盖（tasks 2.5 / 3.3）：
- 封闭决策矩阵（_turn_limit_action）：
  1. 有新提交活性 → extend（含 turn_extension 事件留痕的轮询环端到端）
  2. 仅 tool_result 流量活性 → extend
  3. 双无活性 → kill（error 终态为文件最后一行）
  4. 续期封顶耗尽 → 直接 kill（即便仍有活性）
  5. rev-list 失败 fail-open 不误杀
- 消耗观测口径（tasks 3.1/3.2）：
  6. _extract_usage_info(None) 带 unobserved 标识且四数值键全零
  7. 正常 result 路径无 unobserved 键（非 dict result 置位）
  8. _accumulate_token_usage 对 unobserved 输入零增量
- 超时矩阵互不干扰（design D3）：_turn_limit_action 与超时判定独立（轮询环
  顺序 取消→超时→轮次→poll 不变，由既有 timeout 单测回归覆盖，此处断言
  turn_extension 事件与 timeout_extension 事件互不复用）。

基于真实 git 仓库 fixture + fake Popen 驱动真实 _run_claude 轮询环（与
test_run_latency_stats 同构），不启动真实 daemon/子进程。
"""

import io
import json
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from core.agent_runner.runner import (
    TURN_EXTENSION_MAX,
    TURN_EXTENSION_STEP_FRACTION,
    TURN_EXTENSION_WINDOW_SECONDS,
)
from core.agent_runner.session import SessionTracker
from core.wip_checkpoint import ANCHOR_TURN_LIMIT, WIP_COMMIT_PREFIX
from tests.helpers import FakeLogger, make_runner as make_basic_runner


# ── git repo fixture（与 test_impl_wip_checkpoint 同构） ──────────────────────


def git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@fenix.local")
    git(root, "config", "user.name", "Fenix Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    git(root, "branch", "-M", "main")


def make_wm(root: Path):
    from core.worktree_manager import WorktreeManager
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger())


def branch_log(root: Path, branch: str) -> list:
    out = git(root, "log", "--format=%s", f"main..{branch}")
    return [l for l in out.stdout.splitlines() if l.strip()]


def ahead_count(root: Path, branch: str) -> int:
    out = git(root, "rev-list", "--count", f"main..{branch}")
    return int(out.stdout.strip() or "0")


# ── runner 构造（与 test_run_latency_stats 同构的轮询环最小实例态） ───────────


def make_turn_runner(proot: Path):
    from core.agent_runner import AgentRunner
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {"agents": {"run_timeout_seconds": 3600}}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._running_agents = {}
    runner._cancel_requested = set()
    runner._cancel_requested_lock = threading.Lock()
    runner._cancel_meta = {}
    return runner


def _evt(etype: str, ts: float | None) -> dict:
    d: dict = {"type": etype}
    if ts is not None:
        d["timestamp"] = ts
    return d


def _now_user_tool_result_evt(n_blocks: int = 1) -> dict:
    """真实 stream-json 形态的 tool_result 承载事件（当前时间戳，命中窗口）：
    ``user`` 事件包裹 ``message.content[]`` 里的 ``tool_result`` content block，
    顶层无 ``tool_result`` 事件（与实测转录 100% 形态一致）。"""
    return {
        "type": "user",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"tu_{i}",
             "content": f"result-{i}"} for i in range(n_blocks)
        ]},
    }


def _now_user_text_evt() -> dict:
    """skill 加载消息形态：``user`` 事件仅含 ``text`` block（非 tool_result），
    不得被判为流量活性。"""
    return {
        "type": "user",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": {"content": [
            {"type": "text", "text": "Base directory for this skill: ..."},
        ]},
    }


def _now_evt(etype: str) -> dict:
    """带当前时间戳的事件（命中尾部流量窗口）。"""
    return _evt(etype, time.time())


def _iso(ts: str) -> str:
    return ts


class _BurstFakeProc:
    """Popen 替身：stdout 一次性产出全部流事件；kill 前 poll() 恒 None。

    读线程会立即读完所有事件（turn_count 即刻达峰），轮询环随后自然连续
    命中轮次上限判定轮——无需真实时序。kill 后 poll 返回 -9。
    """

    def __init__(self, events: list, killed_rc: int = -9):
        self._events = [l for l in events if l is not None]
        self._killed = False
        self._killed_rc = killed_rc
        self.pid = 4242
        self.returncode = None

    @property
    def stdout(self):
        return io.StringIO(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self._events))

    @property
    def stderr(self):
        return io.StringIO("")

    def poll(self):
        return self._killed_rc if self._killed else None

    def wait(self, timeout=None):
        return self._killed_rc if self._killed else None

    def terminate(self):
        self._killed = True

    def kill(self):
        self._killed = True


def _patch_popen(monkeypatch, proc):
    """把 runner 模块的 subprocess.Popen 换成返回 proc 的替身（保留真实 run）。"""
    import subprocess as real_subprocess
    import core.agent_runner.runner as rmod
    ns = SimpleNamespace(
        Popen=lambda *a, **k: proc,
        PIPE=real_subprocess.PIPE,
        TimeoutExpired=real_subprocess.TimeoutExpired,
        SubprocessError=real_subprocess.SubprocessError,
        run=real_subprocess.run,
    )
    monkeypatch.setattr(rmod, "subprocess", ns)
    return ns


def _run_file_lines(proot: Path, run_id: str) -> list:
    run_file = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    try:
        return [ln for ln in run_file.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    except OSError:
        return []


def _last_line(proot: Path, run_id: str) -> dict:
    lines = _run_file_lines(proot, run_id)
    assert lines, "run 文件应非空"
    return json.loads(lines[-1])


# ── 封闭决策矩阵（task 2.2 单测） ───────────────────────────────────────────


class TestTurnLimitMatrix:
    def test_new_branch_commits_extends_without_traffic(self, tmp_path):
        """有新提交活性 → extend；即使尾部窗口无 tool_result 流量。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        # 分支有真实提交（相对 main 基线）
        (wt / "work.py").write_text("COMMIT-1\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "[fenix] demo: work")
        assert ahead_count(root, branch) >= 1

        runner = make_turn_runner(root)
        # 空 run 文件（无流量活性）
        run_file = root / ".fenix" / "runs" / "impl-demo-1-a1.jsonl"
        run_file.parent.mkdir(parents=True, exist_ok=True)
        run_file.write_text("", encoding="utf-8")

        action = runner._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 0, wt,
            max_turns=400)
        assert action["action"] == "extend"
        assert action["extension_index"] == 1
        assert action["turn_step"] == int(400 * TURN_EXTENSION_STEP_FRACTION)  # 100
        assert action["new_turn_cap"] == 500
        assert "commit" in action["evidence"].lower() or action["evidence"]

    def test_tool_result_traffic_only_extends(self, tmp_path):
        """仅 tool_result 流量活性 → extend（builtin 验证期场景：无提交有流量）。

        走真实 stream-json 形态：``user`` 事件包裹 ``tool_result`` content
        block（无顶层 tool_result 事件）——原判定仅认顶层 ``tool_result``
        恒判无活性，本用例即回归该盲区。
        """
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_turn_runner(root)
        run_file = root / ".fenix" / "runs" / "impl-demo-1-a1.jsonl"
        run_file.parent.mkdir(parents=True, exist_ok=True)
        # 尾部窗口内真实形态 tool_result 事件（user 包裹 block + 当前时间戳）
        with run_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_now_user_tool_result_evt()) + "\n")

        action = runner._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 0, root / "nonexistent-wt",
            max_turns=400)
        assert action["action"] == "extend"
        assert action["extension_index"] == 1
        assert action["new_turn_cap"] == 500
        # 证据摘要标注 tool_result 流量（证据 b 真实命中）
        assert "tool_result traffic" in action["evidence"]

    def test_plain_text_user_event_not_traffic(self, tmp_path):
        """纯 text user 事件（skill 加载消息）不判流量活性 → kill。

        tool-result-stream-detection 负向场景：`user` 事件仅含 ``text`` block
        不得产生假流量（该续不续、该杀不杀）。
        """
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_turn_runner(root)
        run_file = root / ".fenix" / "runs" / "impl-demo-1-a1.jsonl"
        run_file.parent.mkdir(parents=True, exist_ok=True)
        with run_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_now_user_text_evt()) + "\n")

        action = runner._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 0, root / "nonexistent-wt",
            max_turns=400)
        assert action["action"] == "kill"
        assert "no liveness" in action["evidence"]

    def test_turn_traffic_active_real_shape(self, tmp_path):
        """_turn_traffic_active 对真实形态直接判 True（单测级，无矩阵耦合）。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_turn_runner(root)
        run_file = root / ".fenix" / "runs" / "impl-demo-1-a1.jsonl"
        run_file.parent.mkdir(parents=True, exist_ok=True)
        # 真实形态：user 包裹 tool_result（含 2 个并行 block，仍计一次流量）
        with run_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_now_user_tool_result_evt(n_blocks=2)) + "\n")
        assert runner._turn_traffic_active(run_file) is True

    def test_turn_traffic_active_plain_text_false(self, tmp_path):
        """_turn_traffic_active 对纯 text user 事件判 False（负向单测）。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_turn_runner(root)
        run_file = root / ".fenix" / "runs" / "impl-demo-1-a1.jsonl"
        run_file.parent.mkdir(parents=True, exist_ok=True)
        with run_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_now_user_text_evt()) + "\n")
        assert runner._turn_traffic_active(run_file) is False

    def test_no_liveness_kills(self, tmp_path):
        """双无活性 → kill（空分支、无流量）。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_turn_runner(root)
        run_file = root / ".fenix" / "runs" / "impl-demo-1-a1.jsonl"
        run_file.parent.mkdir(parents=True, exist_ok=True)
        (root / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        run_file.write_text("", encoding="utf-8")

        action = runner._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 0, root / "nonexistent-wt",
            max_turns=400)
        assert action["action"] == "kill"
        assert "no liveness" in action["evidence"]

    def test_cap_exhausted_kills_directly(self, tmp_path):
        """续期封顶耗尽 → 直接 kill，即便仍有活性证据（封顶语义优先）。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_turn_runner(root)
        run_file = root / ".fenix" / "runs" / "impl-demo-1-a1.jsonl"
        run_file.parent.mkdir(parents=True, exist_ok=True)
        with run_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_now_evt("tool_result")) + "\n")

        action = runner._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", TURN_EXTENSION_MAX, None,
            max_turns=400)
        assert action["action"] == "kill"
        assert "budget exhausted" in action["evidence"]

    def test_rev_list_failure_fail_open(self, monkeypatch, tmp_path):
        """rev-list 失败 fail-open 不误杀：worktree 有效但计数命令失败 → 视为
        有活性 → extend（分支状态不可知时不得判死，封顶次数兜住最坏情况）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        (wt / "work.py").write_text("COMMIT-1\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "[fenix] demo: work")

        runner = make_turn_runner(root)
        run_file = root / ".fenix" / "runs" / "impl-demo-1-a1.jsonl"
        run_file.parent.mkdir(parents=True, exist_ok=True)
        run_file.write_text("", encoding="utf-8")  # 无流量活性

        import subprocess as real_subprocess
        import core.agent_runner.runner as rmod
        real_run = real_subprocess.run

        def _revlist_broken(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("cmd")
            if isinstance(cmd, list) and cmd and "rev-list" in cmd:
                raise OSError("simulated rev-list unavailable")
            return real_run(*args, **kwargs)

        ns = SimpleNamespace(
            Popen=real_subprocess.Popen,
            PIPE=real_subprocess.PIPE,
            TimeoutExpired=real_subprocess.TimeoutExpired,
            SubprocessError=real_subprocess.SubprocessError,
            run=_revlist_broken,
        )
        monkeypatch.setattr(rmod, "subprocess", ns)
        action = runner._turn_limit_action(
            run_file, "demo", "impl-demo-1-a1", 0, wt,
            max_turns=400)
        assert action["action"] == "extend"  # fail-open：不误杀


# ── 轮询环端到端（task 2.3 驱动真实 _run_claude） ───────────────────────────


class TestTurnExtensionPollLoop:
    """Scenario: 轮次续期留痕 / 无活性直接杀 / 续期与超时矩阵互不干扰。"""

    def test_turn_extension_events_and_error_last_line(self, monkeypatch, tmp_path):
        """轮询环端到端：流量活性 → 两轮续期（turn_extension 事件落盘）→ 封顶
        kill；error 终态行为与现行一致（error 行是文件最后一行）。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_turn_runner(proot)
        max_turns = 5
        # 8 个 assistant（足够触发 3 次判定：extend、extend、kill）+ 1 个流量 tool_result
        events = (
            [_now_evt("tool_result")]
            + [_evt("assistant", None) for _ in range(8)]
        )
        proc = _BurstFakeProc(events)
        _patch_popen(monkeypatch, proc)

        with pytest.raises(RuntimeError) as cm:
            runner._run_claude(
                "prompt", proot, "impl-demo-99-a1",
                max_turns=max_turns, spec_name="demo", agent_type="implementer")
        err = str(cm.value)
        assert "Max turns" in err

        run_file = proot / ".fenix" / "runs" / "impl-demo-99-a1.jsonl"
        lines = [l for l in run_file.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        ext_events = [
            json.loads(l) for l in lines
            if json.loads(l).get("type") == "turn_extension"
        ]
        # turn_extension 事件留痕：两轮续期（extension 1、2），步长=25% 上限量
        assert len(ext_events) == 2
        assert ext_events[0]["extension"] == 1
        assert ext_events[1]["extension"] == 2
        step = int(max_turns * TURN_EXTENSION_STEP_FRACTION)
        assert ext_events[0]["turn_step"] == step
        assert ext_events[0]["new_turn_cap"] == max_turns + step
        assert len(ext_events[0].get("evidence") or "") <= 400
        # 无 timeout_extension 事件（续期计数与超时语义隔离）
        assert not [l for l in lines if json.loads(l).get("type") == "timeout_extension"]
        # error 终态行为与现行一致：error 行是文件最后一行
        last = json.loads(lines[-1])
        assert last["type"] == "error"
        assert "Max turns" in last["error"]

    def test_real_shape_traffic_extends_in_poll_loop(self, monkeypatch, tmp_path):
        """真实形态端到端：流式 user 包裹 tool_result 事件经 _read_stream 落盘，
        轮询环 _turn_traffic_active 读回判活性 → 续期留痕（非恒 False 失明）。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_turn_runner(proot)
        max_turns = 5
        # 真实形态流量事件 + 8 个 assistant（触发 3 次判定：extend、extend、kill）
        events = [
            _now_user_tool_result_evt(),
        ] + [_evt("assistant", None) for _ in range(8)]
        proc = _BurstFakeProc(events)
        _patch_popen(monkeypatch, proc)

        with pytest.raises(RuntimeError) as cm:
            runner._run_claude(
                "prompt", proot, "impl-demo-95-a1",
                max_turns=max_turns, spec_name="demo", agent_type="implementer")
        assert "Max turns" in str(cm.value)

        run_file = proot / ".fenix" / "runs" / "impl-demo-95-a1.jsonl"
        lines = [l for l in run_file.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        ext_events = [
            json.loads(l) for l in lines
            if json.loads(l).get("type") == "turn_extension"
        ]
        # 真实形态流量 → 至少一次续期，且证据标注 tool_result 流量
        assert len(ext_events) >= 1
        assert "tool_result traffic" in ext_events[0]["evidence"]
        # 落盘的 user 事件确实是真实形态（读线程原样写盘）
        user_evts = [json.loads(l) for l in lines
                     if json.loads(l).get("type") == "user"]
        assert any(
            u["message"]["content"][0]["type"] == "tool_result" for u in user_evts)

    def test_no_liveness_kills_and_error_last_line(self, monkeypatch, tmp_path):
        """无活性 run（空分支 + 无流量）→ 直达 kill，无 turn_extension 事件；
        error 终态行为与现行一致（error 行是文件最后一行）。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_turn_runner(proot)
        proc = _BurstFakeProc([_evt("assistant", None) for _ in range(6)])
        _patch_popen(monkeypatch, proc)

        with pytest.raises(RuntimeError) as cm:
            runner._run_claude(
                "prompt", proot, "impl-demo-98-a1",
                max_turns=5, spec_name="demo", agent_type="implementer")
        err = str(cm.value)
        assert "Max turns" in err

        run_file = proot / ".fenix" / "runs" / "impl-demo-98-a1.jsonl"
        lines = [l for l in run_file.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        assert not [l for l in lines if json.loads(l).get("type") == "turn_extension"]
        last = json.loads(lines[-1])
        assert last["type"] == "error"
        assert "Max turns" in last["error"]

    def test_anchor_c_checkpoint_on_kill(self, monkeypatch, tmp_path):
        """无活性 kill 后锚点 C 生效：worktree dirty 时收口前产生
        fenix(wip): checkpoint turn-limit <spec> 提交（现场保全）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        runner = make_turn_runner(root)
        # 未提交现场（零分支提交型 run）
        (wt / "artifact.py").write_text("WIP-C\n", encoding="utf-8")
        assert ahead_count(root, branch) == 0

        proc = _BurstFakeProc([_evt("assistant", None) for _ in range(6)])
        _patch_popen(monkeypatch, proc)
        with pytest.raises(RuntimeError):
            runner._run_claude(
                "prompt", wt, "impl-demo-97-a1",
                max_turns=5, spec_name="demo", agent_type="implementer")

        # 锚点 C 提交：fenix(wip): checkpoint turn-limit demo
        assert ahead_count(root, branch) == 1
        msgs = branch_log(root, branch)
        assert msgs[0].startswith(
            f"{WIP_COMMIT_PREFIX} checkpoint {ANCHOR_TURN_LIMIT} demo")

    def test_timeout_and_turn_counters_independent(self, monkeypatch, tmp_path):
        """design D3：超时矩阵不被轮次续期复用——travel 时间使 deadline 已过，
        无活性（无流量）时走超时路径 kill，而非轮次矩阵；轮次计数不干扰。"""
        proot = tmp_path / "proj"
        proot.mkdir()
        runner = make_turn_runner(proot)
        # deadline = started_at + 3600；fake proc 卡在 alive（poll None）
        proc = _BurstFakeProc([_evt("assistant", None) for _ in range(3)])
        _patch_popen(monkeypatch, proc)

        orig_now = time.time

        class _AdvancingClock:
            """首轮返回真实 now（deadline 计算），随后返回 beyond-deadline 时刻。"""

            def __init__(self):
                self._base = orig_now()
                self._calls = 0

            def __call__(self):
                self._calls += 1
                return self._base if self._calls <= 1 else self._base + 4000

        fake_clock = _AdvancingClock()
        monkeypatch.setattr("core.agent_runner.runner.time.time", fake_clock)

        with pytest.raises(RuntimeError) as cm:
            runner._run_claude(
                "prompt", proot, "impl-demo-96-a1",
                max_turns=5, spec_name="demo", agent_type="implementer")
        err = str(cm.value)
        assert "Timeout" in err  # 超时收口，而非 Max turns

        run_file = proot / ".fenix" / "runs" / "impl-demo-96-a1.jsonl"
        lines = [l for l in run_file.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        last = json.loads(lines[-1])
        assert last["type"] == "error"
        assert "Timeout" in last["error"]


# ── 消耗观测口径（tasks 3.1/3.2 单测，design D4） ────────────────────────────


class TestUsageUnobserved:
    def test_extract_none_config_unobserved(self, tmp_path):
        """_extract_usage_info(None) 带 unobserved 标识且四数值键全零。"""
        info = SessionTracker._extract_usage_info(None)
        assert info["unobserved"] is True
        assert info["input_tokens"] == 0
        assert info["output_tokens"] == 0
        assert info["cache_creation_input_tokens"] == 0
        assert info["cache_read_input_tokens"] == 0
        assert info["cost_usd"] is None

    def test_extract_regular_result_no_unobserved(self):
        """正常 result 路径无 unobserved 键（观测到的真实消耗）。"""
        ev = {
            "type": "result",
            "usage": {"input_tokens": 10, "output_tokens": 3,
                      "cache_creation_input_tokens": 4,
                      "cache_read_input_tokens": 5},
            "total_cost_usd": 0.42,
        }
        info = SessionTracker._extract_usage_info(ev)
        assert "unobserved" not in info
        assert info["input_tokens"] == 10
        assert info["cost_usd"] == 0.42

    def test_extract_non_dict_config_unobserved(self):
        """非 dict result 同样置位 unobserved（观测兜底）。"""
        for bad in (42, "x", ["a"]):
            info = SessionTracker._extract_usage_info(bad)
            assert info["unobserved"] is True

    def test_accumulate_unobserved_zero_delta(self, tmp_path):
        """_accumulate_token_usage 对 unobserved 输入零增量（不伪造、不累计）。"""
        from core.state_machine import StateMachine
        proot = tmp_path / "proj"
        proot.mkdir()
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        sm = StateMachine(proot / ".fenix" / "STATE.md", FakeLogger())
        sm.add_spec("spec-u", {
            "priority": 5, "status": "implementing",
            "_tokens_in": 100, "_tokens_out": 50,
        })

        runner = make_basic_runner(proot)
        runner.state_machine = sm
        runner._token_accountant._accumulate_token_usage(
            "spec-u", runner._extract_usage_info(None))
        entry = sm.read_one("spec-u")
        assert int(entry["_tokens_in"]) == 100, "unobserved 不得虚增"
        assert int(entry["_tokens_out"]) == 50
        # unobserved 留痕计数递增（审计区分「零消耗」与「未观测」）
        assert runner._token_accountant._unobserved_runs == 1

    def test_accumulate_then_observed_mixed(self, tmp_path):
        """unobserved 之后正常 usage 仍照常累计（跳过不串扰后续记账）。"""
        from core.state_machine import StateMachine
        proot = tmp_path / "proj"
        proot.mkdir()
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        sm = StateMachine(proot / ".fenix" / "STATE.md", FakeLogger())
        sm.add_spec("spec-m", {
            "priority": 5, "status": "implementing",
            "_tokens_in": 0, "_tokens_out": 0,
        })

        runner = make_basic_runner(proot)
        runner.state_machine = sm
        runner._token_accountant._accumulate_token_usage(
            "spec-m", SessionTracker._extract_usage_info(None))  # unobserved
        runner._token_accountant._accumulate_token_usage(
            "spec-m", {
                "input_tokens": 7, "output_tokens": 2,
                "cache_creation_input_tokens": 1, "cache_read_input_tokens": 0,
                "cost_usd": None,
            })
        entry = sm.read_one("spec-m")
        assert int(entry["_tokens_in"]) == 8  # 0 + 7 + 1（cache_creation）
        assert int(entry["_tokens_out"]) == 2
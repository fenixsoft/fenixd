"""add-fast-track-scale-precheck — 规模预估纯函数 + 派发预检 + extension 末位保全单测。

覆盖 spec（evo-add-fast-track-scale-precheck）核心 requirement：

1. 派发前规模分档（Requirement 1）：
   - 1.1 estimate_spec_scale 边界（小样/大样/输入缺失放行）
   - 1.2 budget_tier_for_scale 边界（normal/higher/full）
   - 2.1 _fast_track_scale_precheck + _downgrade_fast_track_scale
2. extension 末位自动 WIP 保全（Requirement 2）：
   - 3.1 _wip_checkpoint_on_extension_tail（消息契约 + git 失败降级 + 无载体跳过）
   - 3.2 轮询环端到端触发（剩余时间进入末位窗口 → 触发 checkpoint）
3. 小 spec 行为零变化（回归）：normal 档走原路径，不降级、不写标记。

基于真实 git 仓库 fixture（与 test_impl_wip_checkpoint 同构）+ FakeLogger。
"""

import json
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.fast_track_result import (
    HIGHER_THRESHOLD,
    NORMAL_THRESHOLD,
    SOURCE_FILE_WEIGHT,
    TASK_WEIGHT,
    budget_tier_for_scale,
    estimate_spec_scale,
)
from core.wip_checkpoint import ANCHOR_EXTENSION_TAIL, WIP_COMMIT_PREFIX
from tests.helpers import FakeLogger, make_runner


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


# ── 纯函数单测：estimate_spec_scale / budget_tier_for_scale ────────────────────


class TestEstimateSpecScale:
    """estimate_spec_scale 边界单测：任务条数 + 源码文件数加权、输入缺失保守低档。"""

    def test_small_spec_low_scale(self, tmp_path):
        """小样：1 未勾任务 + 少源码 → scale 低 → tier=normal。"""
        spec_dir = tmp_path / "small"
        spec_dir.mkdir()
        tasks = spec_dir / "tasks.md"
        tasks.write_text("## 1. x\n- [ ] 1.1 do it\n", encoding="utf-8")
        # 无源码文件
        scale = estimate_spec_scale(spec_dir)
        tier = budget_tier_for_scale(scale)
        assert scale == 1 * TASK_WEIGHT + 0 * SOURCE_FILE_WEIGHT
        assert tier == "normal"

    def test_large_spec_high_scale(self, tmp_path):
        """大样：8 未勾任务 + 5 个源码文件 → scale 高 → tier=full。"""
        spec_dir = tmp_path / "large"
        spec_dir.mkdir()
        tasks = spec_dir / "tasks.md"
        lines = ["## 1. x"]
        for i in range(1, 9):
            lines.append(f"- [ ] {i}.x do {i}")
        tasks.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # 5 个源码文件
        for i in range(5):
            (spec_dir / f"code{i}.py").write_text(f"# file {i}\n", encoding="utf-8")
        scale = estimate_spec_scale(spec_dir)
        tier = budget_tier_for_scale(scale)
        expected_scale = 8 * TASK_WEIGHT + 5 * SOURCE_FILE_WEIGHT
        assert scale == expected_scale
        assert tier == "full"

    def test_medium_spec_higher_tier(self, tmp_path):
        """中等：4 未勾任务 → scale=40 → tier=higher。"""
        spec_dir = tmp_path / "medium"
        spec_dir.mkdir()
        tasks = spec_dir / "tasks.md"
        lines = ["## 1. x"]
        for i in range(1, 5):
            lines.append(f"- [ ] {i}.x do {i}")
        tasks.write_text("\n".join(lines) + "\n", encoding="utf-8")
        scale = estimate_spec_scale(spec_dir)
        tier = budget_tier_for_scale(scale)
        assert scale == 4 * TASK_WEIGHT
        assert tier == "higher"

    def test_tasks_md_missing_safe_low(self, tmp_path):
        """tasks.md 缺失 → WARNING + 低档（不抛异常），返回源码文件数。"""
        spec_dir = tmp_path / "no-tasks"
        spec_dir.mkdir()
        (spec_dir / "a.py").write_text("# a\n", encoding="utf-8")
        scale = estimate_spec_scale(spec_dir)
        tier = budget_tier_for_scale(scale)
        # tasks.md 缺失 → unchecked_count=0 → scale=1
        assert scale == 1 * SOURCE_FILE_WEIGHT
        assert tier == "normal"

    def test_tasks_md_read_failure_safe_low(self, tmp_path):
        """tasks.md 读取失败（二进制内容）→ WARNING + 低档。"""
        spec_dir = tmp_path / "bad-tasks"
        spec_dir.mkdir()
        tasks = spec_dir / "tasks.md"
        tasks.write_bytes(b"\x00\x01\x02binary content")
        scale = estimate_spec_scale(spec_dir)
        tier = budget_tier_for_scale(scale)
        assert scale == 0 * TASK_WEIGHT
        assert tier == "normal"

    def test_spec_dir_not_exist_returns_zero(self, tmp_path):
        """spec 目录不存在 → 返回 0。"""
        scale = estimate_spec_scale(tmp_path / "nonexistent")
        tier = budget_tier_for_scale(scale)
        assert scale == 0
        assert tier == "normal"

    def test_all_checked_tasks_count_zero(self, tmp_path):
        """所有任务已勾选 → unchecked_count=0 → scale 低。"""
        spec_dir = tmp_path / "all-done"
        spec_dir.mkdir()
        tasks = spec_dir / "tasks.md"
        tasks.write_text(
            "## 1. x\n- [x] 1.1 done\n- [x] 1.2 done\n",
            encoding="utf-8")
        scale = estimate_spec_scale(spec_dir)
        tier = budget_tier_for_scale(scale)
        assert scale == 0 * TASK_WEIGHT
        assert tier == "normal"


class TestBudgetTierForScale:
    """budget_tier_for_scale 阈值边界。"""

    def test_normal_boundary(self):
        """scale=29 < 30 → normal。"""
        assert budget_tier_for_scale(29) == "normal"

    def test_higher_boundary(self):
        """scale=30 == NORMAL_THRESHOLD*10 → higher。"""
        assert budget_tier_for_scale(NORMAL_THRESHOLD * TASK_WEIGHT) == "higher"

    def test_higher_upper(self):
        """scale=59 < 60 → higher。"""
        assert budget_tier_for_scale(HIGHER_THRESHOLD * TASK_WEIGHT - 1) == "higher"

    def test_full_boundary(self):
        """scale=60 == HIGHER_THRESHOLD*10 → full。"""
        assert budget_tier_for_scale(HIGHER_THRESHOLD * TASK_WEIGHT) == "full"

    def test_large_scale_still_full(self):
        """scale=200 → full。"""
        assert budget_tier_for_scale(200) == "full"

    def test_zero_scale_normal(self):
        assert budget_tier_for_scale(0) == "normal"


# ── dispatch 层 _fast_track_scale_precheck / _downgrade_fast_track_scale ────────


class TestFastTrackScalePrecheck:
    """dispatch 层预检 + 降级逻辑。"""

    def _make_dispatcher(self, tmp_path, specs=None):
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine

        logger = FakeLogger()
        sm = StateMachine(tmp_path / ".fenix" / "STATE.md", logger)
        engine = PMEngine(sm, MagicMock(), {}, tmp_path, logger)
        engine.handle_event = MagicMock()
        engine._on_spec_verified = MagicMock()
        engine._enqueue = MagicMock()
        engine._enqueue_front = MagicMock()
        # mock worktree manager
        wm = MagicMock()
        wm.ensure_spec_committed.return_value = True
        wm.merge_back_from_branch.return_value = (True, "")
        wm.consume_legacy = MagicMock()
        wm.has_active_worktree.return_value = False
        wm.last_stash_pop_conflicts = []
        engine.agent_runner.worktree_manager = wm
        engine._increment_impl_run_budget_used = MagicMock()
        # 创建 dispatcher 实例并直接 mock 其方法
        from core.pm_engine.dispatch import Dispatcher
        dispatcher = Dispatcher(engine)
        dispatcher._run_fast_track_worker = MagicMock()
        # 使用 wraps 让 _downgrade_fast_track_scale 执行真实实现但可追踪调用
        dispatcher._downgrade_fast_track_scale = MagicMock(
            wraps=dispatcher._downgrade_fast_track_scale
        )
        # 将 dispatcher 实例注入到 engine 的缓存中
        engine.__dict__["_dispatcher_instance"] = dispatcher

        # 写入 spec 目录（tasks.md）
        for name in (specs or ["demo"]):
            spec_dir = tmp_path / "spec" / "changes" / name
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / ".spec.yaml").write_text(
                "schema: spec-driven\ncreated: 2026-09-13\nmode: fast-track\n",
                encoding="utf-8",
            )
            tasks = spec_dir / "tasks.md"
            tasks.write_text("## 1. x\n- [ ] 1.1 do it\n", encoding="utf-8")
            sm.add_spec(name, {"priority": 5})
            sm.transition(name, "ready")

        return engine

    def test_normal_tier_passes_through(self, tmp_path):
        """normal 档：scale 小 → 不降级、不写标记、调用 _run_fast_track_worker。"""
        engine = self._make_dispatcher(tmp_path)
        # 小任务（1 任务）
        tasks = tmp_path / "spec" / "changes" / "demo" / "tasks.md"
        tasks.write_text("## 1. x\n- [ ] 1.1 do it\n", encoding="utf-8")
        engine._run_agent_worker("demo", "fast-track", 5)
        # 检查 spec 状态：不降级（status 保持 ready，因为 worker 不负责 transition）
        entry = engine.state_machine.read_one("demo")
        assert entry["status"] == "ready"
        assert "_fast_track_scale_tier" not in entry
        # dispatcher._run_fast_track_worker 被正常调用
        dispatcher = engine.__dict__["_dispatcher_instance"]
        dispatcher._run_fast_track_worker.assert_called_once_with("demo")
        dispatcher._downgrade_fast_track_scale.assert_not_called()

    def test_full_tier_downgrades_to_full_mode(self, tmp_path):
        """full 档：tasks 多 → 降级 full 模式、reset ready + enqueue implementer。"""
        engine = self._make_dispatcher(tmp_path, ["big-spec"])
        # 写入 8 个任务
        tasks = tmp_path / "spec" / "changes" / "big-spec" / "tasks.md"
        lines = ["## 1. x"]
        for i in range(1, 9):
            lines.append(f"- [ ] {i}.x do {i}")
        tasks.write_text("\n".join(lines) + "\n", encoding="utf-8")
        engine._run_agent_worker("big-spec", "fast-track", 5)
        dispatcher = engine.__dict__["_dispatcher_instance"]
        # 不调用 _run_fast_track_worker
        dispatcher._run_fast_track_worker.assert_not_called()
        # spec 状态 reset ready
        entry = engine.state_machine.read_one("big-spec")
        assert entry["status"] == "ready"
        assert "降级完整模式" in (entry.get("error") or "")
        # implementer 被 enqueue
        engine._enqueue.assert_called_with("big-spec", "implementer")
        # 预算未递增
        engine._increment_impl_run_budget_used.assert_not_called()
        # mode 改写为 full
        from core.spec_mode import read_spec_mode
        assert read_spec_mode(tmp_path, "big-spec") == "full"

    def test_higher_tier_writes_marker(self, tmp_path):
        """higher 档：写 _fast_track_scale_tier=higher 标记，继续调用 _run_fast_track_worker。"""
        engine = self._make_dispatcher(tmp_path, ["med-spec"])
        # 写入 4 个任务（scale=40 → higher）
        tasks = tmp_path / "spec" / "changes" / "med-spec" / "tasks.md"
        lines = ["## 1. x"]
        for i in range(1, 5):
            lines.append(f"- [ ] {i}.x do {i}")
        tasks.write_text("\n".join(lines) + "\n", encoding="utf-8")
        engine._run_agent_worker("med-spec", "fast-track", 5)
        dispatcher = engine.__dict__["_dispatcher_instance"]
        dispatcher._run_fast_track_worker.assert_called_once_with("med-spec")
        dispatcher._downgrade_fast_track_scale.assert_not_called()
        entry = engine.state_machine.read_one("med-spec")
        assert entry.get("_fast_track_scale_tier") == "higher"


# ── WIP checkpoint 锚点：extension-tail ────────────────────────────────────────


class TestExtensionTailCheckpoint:
    """_wip_checkpoint_on_extension_tail：消息契约 + git 失败降级 + 无载体跳过。"""

    def test_checkpoint_commit_branch_ahead(self, tmp_path):
        """dirty worktree → 产生 fenix(wip): checkpoint extension-tail <spec> 提交。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "work.py").write_text("WIP-EXT\n", encoding="utf-8")
        assert ahead_count(root, branch) == 0

        runner = make_runner(root, {})
        runner._wip_checkpoint_on_extension_tail("demo", wt)

        assert ahead_count(root, branch) == 1
        msgs = branch_log(root, branch)
        assert msgs[0] == f"{WIP_COMMIT_PREFIX} checkpoint {ANCHOR_EXTENSION_TAIL} demo"
        assert (wt / "work.py").read_text(encoding="utf-8") == "WIP-EXT\n"

    def test_clean_worktree_no_commit(self, tmp_path):
        """干净 worktree → 零动作（不产生空提交）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        assert ahead_count(root, branch) == 0

        runner = make_runner(root, {})
        runner._wip_checkpoint_on_extension_tail("demo", wt)

        assert ahead_count(root, branch) == 0
        assert not branch_log(root, branch)

    def test_no_worktree_skip(self, tmp_path):
        """无 worktree 载体（None）→ 跳过，不抛错。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_runner(root, {})
        runner._wip_checkpoint_on_extension_tail("demo", None)  # 不得抛错
        assert git(root, "log", "--format=%s", "main").stdout.strip() == "[fenix] base"

    def test_invalid_worktree_skip(self, tmp_path):
        """worktree 路径失效（非 git 目录）→ 跳过，不抛错。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_runner(root, {})
        runner._wip_checkpoint_on_extension_tail("demo", root / "nonexistent")
        assert git(root, "log", "--format=%s", "main").stdout.strip() == "[fenix] base"

    def test_helper_failure_does_not_block(self, monkeypatch, tmp_path):
        """git 超时失败 → WARNING 降级、不抛错、无提交。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "work.py").write_text("WIP-FAIL\n", encoding="utf-8")

        import core.agent_runner.runner as runner_mod

        def _boom(*a, **k):
            raise subprocess.TimeoutExpired("git status --porcelain", 15)

        monkeypatch.setattr(runner_mod, "commit_wip_checkpoint", _boom)
        runner = make_runner(root, {})
        runner._wip_checkpoint_on_extension_tail("demo", wt)  # 不得抛错
        assert ahead_count(root, branch) == 0, "超时降级不产生提交"
        assert (wt / "work.py").read_text(encoding="utf-8") == "WIP-FAIL\n", \
            "未提交现场保留在 worktree"

    def test_higher_tier_extension_limit_increased(self, tmp_path):
        """higher 档标记 → _supervision_deadline_action 中 max_extensions +2。"""
        from core.agent_runner.liveness import LivenessSupervisor, SUPERVISION_DEFAULTS
        from core.agent_runner import AgentRunner

        # 构造最小 LivenessSupervisor
        runner = AgentRunner.__new__(AgentRunner)
        runner.config = {"agents": {"run_timeout_seconds": 9000}}
        runner.state_machine = MagicMock()
        runner.state_machine.read_one.return_value = {
            "_fast_track_scale_tier": "higher"}
        runner.logger = FakeLogger()
        runner.project_root = tmp_path

        supervisor = LivenessSupervisor(runner)
        sup = supervisor._supervision_settings()
        assert sup == SUPERVISION_DEFAULTS  # 基础配置

        # 模拟 _supervision_deadline_action 读取 spec 标记后 max_extensions 提高
        entry = runner.state_machine.read_one("demo")
        assert entry.get("_fast_track_scale_tier") == "higher"

        # 验证 max_extensions 计算：默认 2 + 2 = 4
        base_ext = max(0, int(SUPERVISION_DEFAULTS["max_extensions"]))
        if entry.get("_fast_track_scale_tier") == "higher":
            base_ext += 2
        assert base_ext == 4, "higher 档 max_extensions 应为 4"


# ── 轮询环端到端：extension 末位窗口触发 ────────────────────────────────────


class _BurstFakeProc:
    """Popen 替身：stdout 一次性产出全部流事件；kill 前 poll() 恒 None。"""
    def __init__(self, events, killed_rc=-9):
        self._events = [l for l in events if l is not None]
        self._killed = False
        self._killed_rc = killed_rc
        self.pid = 4242
        self.returncode = None

    @property
    def stdout(self):
        import io
        return io.StringIO(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self._events))

    @property
    def stderr(self):
        import io
        return io.StringIO("")

    def poll(self):
        return self._killed_rc if self._killed else None

    def wait(self, timeout=None):
        return self._killed_rc if self._killed else None

    def terminate(self):
        self._killed = True

    def kill(self):
        self._killed = True


def _evt(etype, ts=None):
    d = {"type": etype}
    if ts is not None:
        d["timestamp"] = ts
    return d


def _patch_popen(monkeypatch, proc):
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


def _make_turn_runner(proot: Path):
    from core.agent_runner import AgentRunner
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {"agents": {"run_timeout_seconds": 6000}}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._running_agents = {}
    runner._cancel_requested = set()
    runner._cancel_requested_lock = threading.Lock()
    runner._cancel_meta = {}
    return runner


class TestExtensionTailPollLoop:
    """轮询环端到端：extension 末位窗口进入 → 触发 checkpoint → 再超时收口。"""

    def test_extension_tail_checkpoint_triggered(self, monkeypatch, tmp_path):
        """fast-track run + 剩余时间 < 窗口 → 触发 extension-tail checkpoint，
        然后超时收口（error 最后一行）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "work.py").write_text("WORK\n", encoding="utf-8")

        runner = _make_turn_runner(tmp_path)
        runner.worktree_manager = wm

        # 构造 burst 事件（一个 assistant 事件）
        proc = _BurstFakeProc([_evt("assistant", None)])
        _patch_popen(monkeypatch, proc)

        # 记录 _wip_checkpoint_on_extension_tail 是否被调用
        checkpoint_called = {"count": 0}
        original_fn = runner._wip_checkpoint_on_extension_tail
        def _spy(spec_name, wt_path):
            checkpoint_called["count"] += 1
            return original_fn(spec_name, wt_path)
        runner._wip_checkpoint_on_extension_tail = _spy

        # timeout 很短（10s），使得 remaining 初始值 < EXTENSION_TAIL_WINDOW_SECONDS
        runner.config = {"agents": {"run_timeout_seconds": 10}}

        # fake time：让 time.time() 快速推进
        real_time = time.time
        fake_start = real_time()
        fake_clock = {"now": fake_start}
        def _fake_time():
            return fake_clock["now"]
        def _fake_sleep(secs):
            fake_clock["now"] += secs
        monkeypatch.setattr("core.agent_runner.runner.time.time", _fake_time)
        monkeypatch.setattr("core.agent_runner.runner.time.sleep", _fake_sleep)

        with pytest.raises(RuntimeError) as cm:
            runner._run_claude(
                "prompt", wt, "impl-demo-99-a1",
                spec_name="demo", agent_type="fast-track")
        assert "Timeout" in str(cm.value)

        # checkpoint 被触发至少一次
        assert checkpoint_called["count"] >= 1, "extension 末位窗口应触发 checkpoint"

        # 分支产生 extension-tail WIP 提交
        assert ahead_count(root, branch) >= 1
        msgs = branch_log(root, branch)
        assert any(ANCHOR_EXTENSION_TAIL in m for m in msgs)

    def test_non_fast_track_no_checkpoint(self, monkeypatch, tmp_path):
        """非 fast-track run → 末位窗口判定不触发 checkpoint。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        (wt / "work.py").write_text("WORK\n", encoding="utf-8")

        runner = _make_turn_runner(tmp_path)
        runner.worktree_manager = wm

        proc = _BurstFakeProc([_evt("assistant", None)])
        _patch_popen(monkeypatch, proc)

        checkpoint_called = {"count": 0}
        original_fn = runner._wip_checkpoint_on_extension_tail
        def _spy(spec_name, wt_path):
            checkpoint_called["count"] += 1
            return original_fn(spec_name, wt_path)
        runner._wip_checkpoint_on_extension_tail = _spy

        runner.config = {"agents": {"run_timeout_seconds": 10}}

        real_time = time.time
        fake_start = real_time()
        fake_clock = {"now": fake_start}
        def _fake_time():
            return fake_clock["now"]
        def _fake_sleep(secs):
            fake_clock["now"] += secs
        monkeypatch.setattr("core.agent_runner.runner.time.time", _fake_time)
        monkeypatch.setattr("core.agent_runner.runner.time.sleep", _fake_sleep)

        with pytest.raises(RuntimeError):
            runner._run_claude(
                "prompt", wt, "impl-demo-98-a1",
                spec_name="demo", agent_type="implementer")  # 不是 fast-track

        assert checkpoint_called["count"] == 0, "非 fast-track 不应触发 checkpoint"

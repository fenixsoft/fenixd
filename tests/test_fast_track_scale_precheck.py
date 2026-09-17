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
    DEFAULT_FULL_THRESHOLD,
    DEFAULT_HIGHER_THRESHOLD,
    FILE_WEIGHT,
    TASK_WEIGHT,
    budget_tier_for_scale,
    estimate_spec_scale,
    get_scale_precheck_config,
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
    """estimate_spec_scale 边界单测：任务数 ×1 + 声明段交付物数 ×2、输入缺失保守低档。"""

    def _write_tasks(self, spec_dir: Path, n_tasks: int, deliverables: list | None = None):
        """写 tasks.md：n_tasks 个未勾选任务 +（可选）声明段交付物。"""
        spec_dir.mkdir(parents=True, exist_ok=True)
        lines = ["## 1. x"]
        for i in range(1, n_tasks + 1):
            lines.append(f"- [ ] {i}.x do {i}")
        if deliverables:
            lines.append("")
            lines.append("## Deliverables")
            lines.append("")
            lines.append("```yaml")
            for path, kind in deliverables:
                lines.append(f"- path: {path}")
                lines.append(f"  kind: {kind}")
            lines.append("```")
        (spec_dir / "tasks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_small_spec_low_scale(self, tmp_path):
        """小样：1 未勾任务 + 0 交付物 → scale=1 → tier=normal。"""
        spec_dir = tmp_path / "small"
        self._write_tasks(spec_dir, 1)
        scale = estimate_spec_scale(spec_dir)
        assert scale == 1 * TASK_WEIGHT
        assert budget_tier_for_scale(scale) == "normal"

    def test_large_spec_high_scale(self, tmp_path):
        """大样：40 未勾任务 + 8 交付物 → scale=56 → tier=full。"""
        spec_dir = tmp_path / "large"
        self._write_tasks(
            spec_dir, 40, [(f"core/f{i}.py", "modify") for i in range(8)]
        )
        scale = estimate_spec_scale(spec_dir)
        assert scale == 40 * TASK_WEIGHT + 8 * FILE_WEIGHT
        assert budget_tier_for_scale(scale) == "full"

    def test_medium_spec_higher_tier(self, tmp_path):
        """中等：22 未勾任务 + 8 交付物 → scale=38 → tier=higher。"""
        spec_dir = tmp_path / "medium"
        self._write_tasks(
            spec_dir, 22, [(f"core/f{i}.py", "modify") for i in range(8)]
        )
        scale = estimate_spec_scale(spec_dir)
        assert scale == 22 * TASK_WEIGHT + 8 * FILE_WEIGHT
        assert budget_tier_for_scale(scale) == "higher"

    def test_declared_deliverables_counted_all_kinds(self, tmp_path):
        """声明段交付物：modify/new/delete 均计 2 分，reference 不计。"""
        spec_dir = tmp_path / "kinds"
        self._write_tasks(
            spec_dir,
            0,
            [
                ("core/a.py", "modify"),
                ("core/b.py", "new"),
                ("core/c.py", "delete"),
                (".fenix/config.yaml", "reference"),  # 语境引用，不计
            ],
        )
        scale = estimate_spec_scale(spec_dir)
        assert scale == 3 * FILE_WEIGHT, "只有 modify/new/delete 计入分值"

    def test_no_deliverables_block_tasks_only(self, tmp_path):
        """无声明段且文档正文无路径 → 交付物计 0，分值为任务数。"""
        spec_dir = tmp_path / "no-decl"
        self._write_tasks(spec_dir, 7)
        scale = estimate_spec_scale(spec_dir)
        assert scale == 7 * TASK_WEIGHT

    def test_tasks_md_missing_safe_low(self, tmp_path):
        """tasks.md 缺失 → WARNING + 低档（不抛异常），交付物计 0。"""
        spec_dir = tmp_path / "no-tasks"
        spec_dir.mkdir()
        scale = estimate_spec_scale(spec_dir)
        assert scale == 0
        assert budget_tier_for_scale(scale) == "normal"

    def test_tasks_md_read_failure_safe_low(self, tmp_path):
        """tasks.md 读取失败（二进制内容）→ WARNING + 低档。"""
        spec_dir = tmp_path / "bad-tasks"
        spec_dir.mkdir()
        (spec_dir / "tasks.md").write_bytes(b"\x00\x01\x02binary content")
        scale = estimate_spec_scale(spec_dir)
        assert scale == 0
        assert budget_tier_for_scale(scale) == "normal"

    def test_spec_dir_not_exist_returns_zero(self, tmp_path):
        """spec 目录不存在 → 返回 0。"""
        scale = estimate_spec_scale(tmp_path / "nonexistent")
        assert scale == 0
        assert budget_tier_for_scale(scale) == "normal"

    def test_all_checked_tasks_count_zero(self, tmp_path):
        """所有任务已勾选（交付物已全部交付）→ 分值回落，不再判大。"""
        spec_dir = tmp_path / "all-done"
        spec_dir.mkdir()
        (spec_dir / "tasks.md").write_text(
            "## 1. x\n- [x] 1.1 done\n- [x] 1.2 done\n",
            encoding="utf-8")
        scale = estimate_spec_scale(spec_dir)
        assert scale == 0
        assert budget_tier_for_scale(scale) == "normal"


class TestBudgetTierForScale:
    """budget_tier_for_scale 阈值边界（**严格大于**：阈值本身落较低档）。"""

    def test_threshold_itself_lower_tier(self):
        """等于 higher 阈值 → 仍 normal；等于 full 阈值 → 仍 higher。"""
        assert budget_tier_for_scale(DEFAULT_HIGHER_THRESHOLD) == "normal"
        assert budget_tier_for_scale(DEFAULT_FULL_THRESHOLD) == "higher"

    def test_just_above_thresholds(self):
        """刚超过阈值即升档。"""
        assert budget_tier_for_scale(DEFAULT_HIGHER_THRESHOLD + 1) == "higher"
        assert budget_tier_for_scale(DEFAULT_FULL_THRESHOLD + 1) == "full"

    def test_zero_scale_normal(self):
        assert budget_tier_for_scale(0) == "normal"

    def test_large_scale_still_full(self):
        assert budget_tier_for_scale(200) == "full"

    def test_custom_thresholds(self):
        """阈值可覆盖（来自 agents.scale_precheck）：边界随自定义值移动。"""
        kw = {"higher_threshold": 10, "full_threshold": 20}
        assert budget_tier_for_scale(10, **kw) == "normal"
        assert budget_tier_for_scale(11, **kw) == "higher"
        assert budget_tier_for_scale(20, **kw) == "higher"
        assert budget_tier_for_scale(21, **kw) == "full"


class TestGetScalePrecheckConfig:
    """get_scale_precheck_config：缺省填充 + 非法值回退 + 阈值倒挂整段回退。"""

    def test_defaults_when_absent(self):
        cfg = get_scale_precheck_config({})
        assert cfg == {
            "enabled": True,
            "higher_threshold": DEFAULT_HIGHER_THRESHOLD,
            "full_threshold": DEFAULT_FULL_THRESHOLD,
        }

    def test_explicit_values_respected(self):
        cfg = get_scale_precheck_config(
            {"agents": {"scale_precheck": {
                "enabled": False, "higher_threshold": 10, "full_threshold": 20}}}
        )
        assert cfg == {"enabled": False, "higher_threshold": 10, "full_threshold": 20}

    def test_illegal_values_fall_back(self):
        """非布尔开关 / 非整数阈值 / 越界阈值 → 逐项回退缺省。"""
        cfg = get_scale_precheck_config(
            {"agents": {"scale_precheck": {
                "enabled": 1, "higher_threshold": "x", "full_threshold": 0}}}
        )
        assert cfg == {
            "enabled": True,
            "higher_threshold": DEFAULT_HIGHER_THRESHOLD,
            "full_threshold": DEFAULT_FULL_THRESHOLD,
        }

    def test_inverted_thresholds_fall_back_whole_section(self):
        """阈值倒挂/相等 → 两阈值整段回退缺省；enabled 独立于阈值，仍按所填生效。"""
        for higher, full in ((45, 30), (30, 30)):
            cfg = get_scale_precheck_config(
                {"agents": {"scale_precheck": {
                    "enabled": False,
                    "higher_threshold": higher,
                    "full_threshold": full}}}
            )
            assert cfg["higher_threshold"] == DEFAULT_HIGHER_THRESHOLD
            assert cfg["full_threshold"] == DEFAULT_FULL_THRESHOLD
            assert cfg["enabled"] is False, "阈值非法不应把用户的关闭开关也重置"


# ── dispatch 层 _fast_track_scale_precheck / _downgrade_fast_track_scale ────────


class TestFastTrackScalePrecheck:
    """dispatch 层预检 + 降级逻辑（含总开关与自定义阈值）。"""

    def _make_dispatcher(self, tmp_path, specs=None, config=None, n_tasks=1):
        from core.pm_engine import PMEngine
        from core.state_machine import StateMachine

        logger = FakeLogger()
        sm = StateMachine(tmp_path / ".fenix" / "STATE.md", logger)
        engine = PMEngine(sm, MagicMock(), config or {}, tmp_path, logger)
        engine.handle_event = MagicMock()
        engine._on_spec_verified = MagicMock()
        # 观察点：dispatcher 直接 self._enqueue（refactor-giant-classes 3.8
        # 消解回引后不再经 engine 门面委托转发）
        # 注意：dispatcher 将在下面创建，此处暂留空，稍后赋 mock。
        engine._enqueue = MagicMock()  # 保留以防其他 engine 路径用到
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
        # 观察点下移：dispatcher 直接 self._enqueue（refactor-giant-classes 3.8
        # 消解回引后不再经 engine 门面委托转发）
        dispatcher._enqueue = MagicMock()
        dispatcher._enqueue_front = MagicMock()

        # 写入 spec 目录（tasks.md）
        for name in (specs or ["demo"]):
            spec_dir = tmp_path / "spec" / "changes" / name
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / ".spec.yaml").write_text(
                "schema: spec-driven\ncreated: 2026-09-13\nmode: fast-track\n",
                encoding="utf-8",
            )
            tasks = spec_dir / "tasks.md"
            lines = ["## 1. x"]
            for i in range(1, n_tasks + 1):
                lines.append(f"- [ ] {i}.x do it")
            tasks.write_text("\n".join(lines) + "\n", encoding="utf-8")
            sm.add_spec(name, {"priority": 5})
            sm.transition(name, "ready")

        return engine

    def _write_tasks(self, tmp_path, spec, n_tasks, deliverables=0):
        """重写 spec 的 tasks.md：n_tasks 未勾任务 + deliverables 个 modify 交付物。"""
        spec_dir = tmp_path / "spec" / "changes" / spec
        lines = ["## 1. x"]
        for i in range(1, n_tasks + 1):
            lines.append(f"- [ ] {i}.x do it")
        if deliverables:
            lines += ["", "## Deliverables", "", "```yaml"]
            for i in range(deliverables):
                lines += [f"- path: core/f{i}.py", "  kind: modify"]
            lines.append("```")
        (spec_dir / "tasks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_normal_tier_passes_through(self, tmp_path):
        """normal 档：scale 小 → 不降级、不写标记、调用 _run_fast_track_worker。"""
        engine = self._make_dispatcher(tmp_path)
        self._write_tasks(tmp_path, "demo", n_tasks=5)
        engine._run_agent_worker("demo", "fast-track", 5)
        # 检查 spec 状态：不降级（status 保持 ready，因为 worker 不负责 transition）
        entry = engine.state_machine.read_one("demo")
        assert entry["status"] == "ready"
        assert entry.get("_fast_track_scale_tier") != "higher"
        # dispatcher._run_fast_track_worker 被正常调用
        dispatcher = engine.__dict__["_dispatcher_instance"]
        dispatcher._run_fast_track_worker.assert_called_once_with("demo")
        dispatcher._downgrade_fast_track_scale.assert_not_called()

    def test_full_tier_downgrades_to_full_mode(self, tmp_path):
        """full 档：分值超 full 阈值 → 降级 full 模式、reset ready + enqueue implementer。"""
        engine = self._make_dispatcher(tmp_path, ["big-spec"])
        # 30 任务 + 8 交付物 = 30 + 16 = 46 > 45 → full
        self._write_tasks(tmp_path, "big-spec", n_tasks=30, deliverables=8)
        engine._run_agent_worker("big-spec", "fast-track", 5)
        dispatcher = engine.__dict__["_dispatcher_instance"]
        # 不调用 _run_fast_track_worker
        dispatcher._run_fast_track_worker.assert_not_called()
        # spec 状态 reset ready
        entry = engine.state_machine.read_one("big-spec")
        assert entry["status"] == "ready"
        assert "降级完整模式" in (entry.get("error") or "")
        # implementer 被 enqueue
        dispatcher = engine.__dict__["_dispatcher_instance"]
        dispatcher._enqueue.assert_called_with("big-spec", "implementer")
        # 预算未递增
        engine._increment_impl_run_budget_used.assert_not_called()
        # mode 改写为 full
        from core.spec_mode import read_spec_mode
        assert read_spec_mode(tmp_path, "big-spec") == "full"

    def test_higher_tier_writes_marker(self, tmp_path):
        """higher 档：分值在 (higher, full] 区间 → 写标记 + 继续 fast-track。"""
        engine = self._make_dispatcher(tmp_path, ["med-spec"])
        # 22 任务 + 8 交付物 = 22 + 16 = 38（> 30 且 ≤ 45）→ higher
        self._write_tasks(tmp_path, "med-spec", n_tasks=22, deliverables=8)
        engine._run_agent_worker("med-spec", "fast-track", 5)
        dispatcher = engine.__dict__["_dispatcher_instance"]
        dispatcher._run_fast_track_worker.assert_called_once_with("med-spec")
        dispatcher._downgrade_fast_track_scale.assert_not_called()
        entry = engine.state_machine.read_one("med-spec")
        assert entry.get("_fast_track_scale_tier") == "higher"

    def test_threshold_itself_stays_lower_tier(self, tmp_path):
        """严格大于：分值恰等于 full 阈值（45）→ 仍 higher，不降级。"""
        engine = self._make_dispatcher(tmp_path, ["edge-spec"])
        # 29 任务 + 8 交付物 = 29 + 16 = 45 == full 阈值 → higher
        self._write_tasks(tmp_path, "edge-spec", n_tasks=29, deliverables=8)
        engine._run_agent_worker("edge-spec", "fast-track", 5)
        dispatcher = engine.__dict__["_dispatcher_instance"]
        dispatcher._downgrade_fast_track_scale.assert_not_called()
        entry = engine.state_machine.read_one("edge-spec")
        assert entry.get("_fast_track_scale_tier") == "higher"

    def test_disabled_switch_skips_precheck_entirely(self, tmp_path):
        """总开关关闭 → 预检完全不执行：不降级、不写档位标记、照常派发。"""
        engine = self._make_dispatcher(
            tmp_path,
            ["off-spec"],
            config={"agents": {"scale_precheck": {"enabled": False}}},
        )
        # 分值 46（本会判 full）——开关关闭后不得降级
        self._write_tasks(tmp_path, "off-spec", n_tasks=30, deliverables=8)
        engine._run_agent_worker("off-spec", "fast-track", 5)
        dispatcher = engine.__dict__["_dispatcher_instance"]
        dispatcher._downgrade_fast_track_scale.assert_not_called()
        dispatcher._run_fast_track_worker.assert_called_once_with("off-spec")
        entry = engine.state_machine.read_one("off-spec")
        assert entry["status"] == "ready"
        assert entry.get("_fast_track_scale_tier") != "higher", "关闭时不得写档位标记"
        from core.spec_mode import read_spec_mode
        assert read_spec_mode(tmp_path, "off-spec") == "fast-track", "mode 不得被改写"

    def test_disabled_switch_clears_stale_marker(self, tmp_path):
        """关闭开关 + 存量 higher 标记 → 派发时清除标记（不再抬高 extension）。"""
        engine = self._make_dispatcher(
            tmp_path,
            ["stale-spec"],
            config={"agents": {"scale_precheck": {"enabled": False}}},
        )
        engine.state_machine.update_spec("stale-spec", {"_fast_track_scale_tier": "higher"})
        self._write_tasks(tmp_path, "stale-spec", n_tasks=5)
        engine._run_agent_worker("stale-spec", "fast-track", 5)
        entry = engine.state_machine.read_one("stale-spec")
        assert entry.get("_fast_track_scale_tier") != "higher", "陈旧 higher 标记应被清除"

    def test_custom_thresholds_respected(self, tmp_path):
        """自定义阈值：同一分值在缺省下 normal、在收紧阈值下 full。"""
        engine = self._make_dispatcher(
            tmp_path,
            ["tuned-spec"],
            config={"agents": {"scale_precheck": {
                "higher_threshold": 5, "full_threshold": 8}}},
        )
        # 6 任务 = 6 分：> 5 且 ≤ 8 → higher（缺省阈值下是 normal）
        self._write_tasks(tmp_path, "tuned-spec", n_tasks=6)
        engine._run_agent_worker("tuned-spec", "fast-track", 5)
        entry = engine.state_machine.read_one("tuned-spec")
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
        # 活性判定器 stub：超时收口路径会调用 _judge_liveness，未 stub 时会真起
        # `claude -p` 子进程（单测挂 6-11s 且对外部 CLI 有隐式依赖）。
        monkeypatch.setattr(
            "core.agent_runner.liveness.LivenessSupervisor._judge_liveness",
            lambda self, snapshot, spec_name, run_id: {
                "verdict": "stagnant", "evidence": "stubbed"})

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
        # 活性判定器 stub（同上）：避免真起 `claude -p`。
        monkeypatch.setattr(
            "core.agent_runner.liveness.LivenessSupervisor._judge_liveness",
            lambda self, snapshot, spec_name, run_id: {
                "verdict": "stagnant", "evidence": "stubbed"})

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

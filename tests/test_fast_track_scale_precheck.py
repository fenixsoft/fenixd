"""evo-add-fast-track-scale-precheck — 规模预估纯函数 + extension-tail WIP 保全 + higher 档提额 单测。

覆盖 spec（fast-track-scale-precheck）全部 Scenario：
  1. 派发前规模分档：小 spec 零变化 / 大 spec 降级或提额 / 输入缺失保守放行
  2. extension 末位自动 WIP 保全：触发 checkpoint 事件 / git 失败降级
  3. higher 档 extension 预算 +1

基于真实 git 仓库 fixture（与 test_impl_wip_checkpoint.py 同构），不启动真实 daemon/子进程。
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.fast_track_result import (
    SCALE_FILE_WEIGHT,
    SCALE_FULL_THRESHOLD,
    SCALE_HIGHER_THRESHOLD,
    SCALE_TIER_FULL,
    SCALE_TIER_HIGHER,
    SCALE_TIER_NORMAL,
    SCALE_TASK_WEIGHT,
    budget_tier_for_scale,
    estimate_spec_scale,
)
from core.wip_checkpoint import (
    ANCHOR_EXTENSION_TAIL,
    WIP_COMMIT_PREFIX,
    commit_wip_checkpoint,
)
from tests.helpers import FakeLogger, make_runner


# ── git repo fixture（与 test_impl_wip_checkpoint.py 同构） ──────────────────


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


# ── helpers: 构造 tasks.md 与 spec 目录 ──────────────────────────────────────


def _mk_spec_dir(tmp_path: Path, tasks_content: str, extra_files: list = None,
                 name: str = "demo"):
    """构造 spec 目录：tasks.md + 可选额外文件 + specs 子目录。"""
    spec_dir = tmp_path / "spec" / "changes" / name
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / ".spec.yaml").write_text(
        f"schema: spec-driven\nmode: fast-track\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(tasks_content, encoding="utf-8")
    for rel in (extra_files or []):
        p = spec_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")
    return spec_dir


# ── 4.1 estimate_spec_scale 边界单测 ─────────────────────────────────────────


class TestEstimateSpecScale:
    def test_small_spec_one_task_no_files(self, tmp_path):
        """1 条未勾选任务 + 0 源码文件 → scale = 10 × 1 = 10 → normal。"""
        spec_dir = _mk_spec_dir(tmp_path, "- [ ] 1.1 do it\n")
        scale = estimate_spec_scale(spec_dir)
        self.assert_(scale == SCALE_TASK_WEIGHT * 1)

    def test_medium_spec_five_tasks_two_files(self, tmp_path):
        """5 条任务 + 2 源码文件 → 5×10 + 2×3 = 56 → higher。"""
        spec_dir = _mk_spec_dir(
            tmp_path,
            tasks_content="\n".join(f"- [ ] {i}.1 task {i}" for i in range(1, 6)),
            extra_files=["specs/foo.py", "specs/bar.ts"],
        )
        scale = estimate_spec_scale(spec_dir)
        expected = 5 * SCALE_TASK_WEIGHT + 2 * SCALE_FILE_WEIGHT
        assert scale == expected

    def test_large_spec_ten_tasks_ten_files(self, tmp_path):
        """10 条任务 + 10 源码文件 → 10×10 + 10×3 = 130 → full。"""
        files = [f"specs/file{i}.py" for i in range(10)]
        spec_dir = _mk_spec_dir(
            tmp_path,
            tasks_content="\n".join(f"- [ ] {i}.1 task {i}" for i in range(1, 11)),
            extra_files=files,
        )
        scale = estimate_spec_scale(spec_dir)
        expected = 10 * SCALE_TASK_WEIGHT + 10 * SCALE_FILE_WEIGHT
        assert scale == expected
        assert scale >= SCALE_FULL_THRESHOLD

    def test_all_checked_tasks_returns_zero(self, tmp_path):
        """所有任务已勾选（- [x]）→ unchecked_tasks=0 → scale=0。"""
        spec_dir = _mk_spec_dir(
            tmp_path,
            tasks_content="- [x] 1.1 done\n- [x] 1.2 done\n",
        )
        assert estimate_spec_scale(spec_dir) == 0

    def test_mixed_checked_unchecked(self, tmp_path):
        """3 已勾 + 2 未勾 → 只计 2 条未勾任务（scale = 20 + 0 文件）。"""
        spec_dir = _mk_spec_dir(
            tmp_path,
            tasks_content="- [x] 1.1 done\n- [ ] 1.2 todo\n"
                          "- [x] 2.1 done\n- [ ] 2.2 todo\n- [x] 3.1 done\n",
        )
        assert estimate_spec_scale(spec_dir) == 2 * SCALE_TASK_WEIGHT

    def test_tasks_md_missing_returns_zero_with_warning(self, tmp_path):
        """tasks.md 缺失 → 0 分 + WARNING。"""
        spec_dir = tmp_path / "spec" / "changes" / "demo"
        spec_dir.mkdir(parents=True)
        logger = MagicMock()
        scale = estimate_spec_scale(spec_dir, logger=logger)
        assert scale == 0
        logger.warning.assert_called_once()
        assert "tasks.md" in str(logger.warning.call_args)

    def test_tasks_md_read_failure_returns_zero(self, tmp_path):
        """tasks.md 存在但读取异常（模拟 UnicodeDecodeError）→ 0 分。"""
        spec_dir = _mk_spec_dir(tmp_path, "corrupt")
        # 覆盖为非法内容（binary）触发 UnicodeDecodeError
        bad_path = spec_dir / "tasks.md"
        bad_path.write_bytes(b"\x00\xfe\xff")
        logger = MagicMock()
        scale = estimate_spec_scale(spec_dir, logger=logger)
        assert scale == 0

    def test_source_files_counted_recursively(self, tmp_path):
        """源码文件按 .py/.ts/.tsx 后缀递归计数，非源码后缀不计。"""
        spec_dir = _mk_spec_dir(
            tmp_path,
            tasks_content="- [ ] 1.1 x\n",
            extra_files=[
                "src/main.py",
                "src/types.ts",
                "src/styles.tsx",
                "docs/readme.md",       # 不计
                "specs/test.txt",       # 不计
                "nested/deep/impl.py",  # 计
            ],
        )
        scale = estimate_spec_scale(spec_dir)
        source_count = 4  # main.py, types.ts, styles.tsx, deep/impl.py
        assert scale == 1 * SCALE_TASK_WEIGHT + source_count * SCALE_FILE_WEIGHT

    def assert_(self, condition, msg=""):
        """简写 assert helper（pytest 环境兼容 unittest 风格）。"""
        assert condition, msg


# ── 4.1 budget_tier_for_scale 边界单测 ───────────────────────────────────────


class TestBudgetTierForScale:
    def test_low_scale_returns_normal(self):
        assert budget_tier_for_scale(0) == SCALE_TIER_NORMAL
        assert budget_tier_for_scale(29) == SCALE_TIER_NORMAL

    def test_boundary_higher_threshold(self):
        assert budget_tier_for_scale(SCALE_HIGHER_THRESHOLD - 1) == SCALE_TIER_NORMAL
        assert budget_tier_for_scale(SCALE_HIGHER_THRESHOLD) == SCALE_TIER_HIGHER

    def test_medium_scale_returns_higher(self):
        assert budget_tier_for_scale(SCALE_HIGHER_THRESHOLD) == SCALE_TIER_HIGHER
        assert budget_tier_for_scale(SCALE_FULL_THRESHOLD - 1) == SCALE_TIER_HIGHER

    def test_boundary_full_threshold(self):
        assert budget_tier_for_scale(SCALE_FULL_THRESHOLD - 1) == SCALE_TIER_HIGHER
        assert budget_tier_for_scale(SCALE_FULL_THRESHOLD) == SCALE_TIER_FULL

    def test_high_scale_returns_full(self):
        assert budget_tier_for_scale(SCALE_FULL_THRESHOLD) == SCALE_TIER_FULL
        assert budget_tier_for_scale(1000) == SCALE_TIER_FULL


# ── 4.2 extension-tail WIP 保全 ──────────────────────────────────────────────


class TestExtensionTailWipCheckpoint:
    def test_extension_tail_checkpoint_creates_wip_commit(self, tmp_path):
        """dirty worktree → 产生 fenix(wip): checkpoint extension-tail <spec> 提交。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)
        (wt / "work.py").write_text("WIP-TAIL\n", encoding="utf-8")
        assert ahead_count(root, branch) == 0

        runner = make_runner(root, {})
        runner._wip_checkpoint_extension_tail("demo", wt)

        assert ahead_count(root, branch) == 1
        msgs = branch_log(root, branch)
        assert msgs[0].startswith(
            f"{WIP_COMMIT_PREFIX} checkpoint {ANCHOR_EXTENSION_TAIL} demo")
        # 内容完整入提交
        content = git(root, "show", f"{branch}:work.py").stdout
        assert content == "WIP-TAIL\n"

    def test_extension_tail_clean_worktree_no_commit(self, tmp_path):
        """干净 worktree → 零动作幂等（不产生提交）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        branch = wm.get_branch_name(wt)

        runner = make_runner(root, {})
        runner._wip_checkpoint_extension_tail("demo", wt)

        assert ahead_count(root, branch) == 0
        assert not branch_log(root, branch)

    def test_extension_tail_no_worktree_skip(self, tmp_path):
        """无 worktree（None）→ 跳过，不抛错。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_runner(root, {})
        runner._wip_checkpoint_extension_tail("demo", None)  # 不抛

    def test_extension_tail_invalid_worktree_skip(self, tmp_path):
        """worktree 路径不存在 → 跳过，不抛错。"""
        root = tmp_path / "repo"
        init_repo(root)
        runner = make_runner(root, {})
        runner._wip_checkpoint_extension_tail("demo", root / "nonexistent")

    def test_extension_tail_git_failure_does_not_throw(self, monkeypatch, tmp_path):
        """git 超时 → 方法不抛，降级 WARNING（不阻断超时收口）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("demo", "implementer")
        (wt / "work.py").write_text("FAIL\n", encoding="utf-8")

        import core.agent_runner.runner as runner_mod

        def _boom(*a, **k):
            raise subprocess.TimeoutExpired("git status --porcelain", 15)

        monkeypatch.setattr(runner_mod, "commit_wip_checkpoint", _boom)
        runner = make_runner(root, {})
        runner._wip_checkpoint_extension_tail("demo", wt)  # 不抛

        branch = wm.get_branch_name(wt)
        assert ahead_count(root, branch) == 0, "git 超时降级不产生提交"


# ── higher 档 extension 预算 +1（liveness.py _effective_max_extensions）──────


class TestEffectiveMaxExtensionsHigherTier:
    def _make_runner_with_state_machine(self, tmp_path, spec_entry=None):
        """构造 minimal runner + state_machine mock，供 _effective_max_extensions 测试。"""
        root = tmp_path / "proj"
        root.mkdir(parents=True, exist_ok=True)
        (root / ".fenix").mkdir(exist_ok=True)
        logger = FakeLogger()
        sm = MagicMock()
        sm.read_one.return_value = spec_entry or {}
        runner = make_runner(root, {"agents": {"timeout_supervision": {"max_extensions": 2}}})
        runner.state_machine = sm
        # 挂到 runner 上的 _pm（门面）访问
        runner._pm = MagicMock()
        runner._pm.state_machine = sm
        return runner

    def test_normal_tier_unchanged(self, tmp_path):
        """spec entry 无 _ft_scale_tier → max_extensions 不变（基准值）。"""
        runner = self._make_runner_with_state_machine(tmp_path, {"status": "implementing"})
        assert runner._liveness._effective_max_extensions("demo") == 2

    def test_higher_tier_plus_one(self, tmp_path):
        """spec entry _ft_scale_tier=higher → max_extensions +1。"""
        runner = self._make_runner_with_state_machine(
            tmp_path, {"_ft_scale_tier": "higher"})
        assert runner._liveness._effective_max_extensions("demo") == 3

    def test_higher_tier_log_full_tier_unchanged(self, tmp_path):
        """spec entry _ft_scale_tier=full → max_extensions 不变（full 降级走 implementer）。"""
        runner = self._make_runner_with_state_machine(
            tmp_path, {"_ft_scale_tier": "full"})
        assert runner._liveness._effective_max_extensions("demo") == 2

    def test_none_spec_name_returns_baseline(self, tmp_path):
        """spec_name=None → 基准值（无标记可读）。"""
        runner = self._make_runner_with_state_machine(tmp_path)
        assert runner._liveness._effective_max_extensions(None) == 2

    def test_state_machine_read_error_returns_baseline(self, tmp_path):
        """state_machine.read_one 抛异常 → 基准值（fail-open）。"""
        runner = self._make_runner_with_state_machine(tmp_path)
        runner._pm.state_machine.read_one.side_effect = RuntimeError("boom")
        assert runner._liveness._effective_max_extensions("demo") == 2

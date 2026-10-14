"""worktree 载体分支形状消歧单测（verify- 开头 spec 名）。

实证事故（2026-10-14 dsh-plugins admin-global-1791999865）：spec 名
``verify-dsh-plugins-live`` 以 ``verify-`` 开头，其实现分支
``fenix/verify-dsh-plugins-live-<ts>`` 命中裸前缀 ``startswith("fenix/verify-")``
形状判定，cleanup finally 收尾只摘 ``:verifier`` 族锁 → 同键
``:implementer`` 锁泄漏 → 后续每轮重派 create() 即撞锁 early give-up
（Failed to create worktree）→ 同因重派循环 → spec 冻结。

覆盖：
  1. branch_shape_is_verifier 三态判定矩阵（结构消歧 + 回落口径）
  2. verify- 开头 spec 的 implementer worktree cleanup(success=True)
     必须释放 :implementer 锁（事故主场景回归）
  3. verify- 开头 spec 的 implementer worktree cleanup(success=False)
     走遗产登记路径（is_implementer 不再被误判为 verifier）
  4. keep_for_reuse 对 verify- 开头 spec 的实现族锁按 non-verifier 族释放
基于真实 git 仓库 fixture（与 test_worktree_reuse 同构）。
"""

from pathlib import Path

import pytest

from core.worktree_manager import WorktreeManager
from core.worktree_manager.shape import branch_shape_is_verifier

from test_agent_runner import FakeLogger


def git(root: Path, *args, check=True):
    import subprocess

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


def make_wm(root: Path) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger())


class TestBranchShapeIsVerifier:
    """branch_shape_is_verifier 三态判定矩阵。"""

    def test_impl_branch_of_verify_prefixed_spec_is_not_verifier(self):
        """事故核心：verify- 开头 spec 名的实现分支，靠目录名/hint 锚判实现族。"""
        lookalike = "fenix/verify-dsh-plugins-live-1791992264"
        # 目录名前缀锚（create 按 agent_type 定，与 spec 名无关，无歧义）
        assert branch_shape_is_verifier(
            lookalike, "impl-verify-dsh-plugins-live-1791992264",
        ) is False
        # spec_hint 锚（调用方上下文真 spec 名）
        assert branch_shape_is_verifier(
            lookalike, spec_hint="verify-dsh-plugins-live",
        ) is False
        # 双锚皆缺：分支自结构不可解歧，维持历史 verifier 判定（文档化局限，
        # 调用方 MUST 提供目录名或 spec_hint 锚）
        assert branch_shape_is_verifier(lookalike) is True

    def test_verifier_branch_of_verify_prefixed_spec_is_verifier(self):
        assert branch_shape_is_verifier(
            "fenix/verify-verify-dsh-plugins-live-1791997596"
        ) is True
        # 目录名锚同样判 verifier 族
        assert branch_shape_is_verifier(
            "fenix/verify-verify-dsh-plugins-live-1791997596",
            "verify-verify-dsh-plugins-live-1791997596",
        ) is True
        # spec_hint 锚：front == verify-<hint> 结构命中
        assert branch_shape_is_verifier(
            "fenix/verify-verify-dsh-plugins-live-1791997596",
            spec_hint="verify-dsh-plugins-live",
        ) is True

    def test_regular_spec_both_families(self):
        """常规 spec 名两族形状与历史口径一致。"""
        assert branch_shape_is_verifier("fenix/add-foo-123") is False
        assert branch_shape_is_verifier("fenix/verify-add-foo-123") is True

    def test_non_timestamp_branch_falls_back_to_prefix(self):
        """末段非纯数字时间戳：回落历史前缀启发式。"""
        assert branch_shape_is_verifier("fenix/verify-something") is True
        assert branch_shape_is_verifier("fenix/impl-something") is False

    def test_wt_name_fallback_when_branch_missing(self):
        """分支锚缺失：回落目录名前缀（历史口径）。"""
        assert branch_shape_is_verifier(None, "verify-verify-x-1") is True
        assert branch_shape_is_verifier(None, "impl-verify-x-1") is False
        assert branch_shape_is_verifier("", "repair-y-2") is None
        assert branch_shape_is_verifier(None, "") is None

    def test_name_used_when_branch_not_fenix_shaped(self):
        """分支非 fenix/ 形态：目录名锚兜底。"""
        assert branch_shape_is_verifier("origin/main", "impl-x-1") is False
        assert branch_shape_is_verifier("origin/main", "verify-x-1") is True
        assert branch_shape_is_verifier("origin/main", "judge-x-1") is None

    def test_dirty_spec_hint_does_not_mislead(self):
        """脏 hint（与分支全不匹配）不强行选边，降锚到目录名。"""
        # hint 是别的 spec：锚 1 不命中 → 目录名锚 impl- 判实现族
        assert branch_shape_is_verifier(
            "fenix/verify-add-foo-1", "impl-verify-add-foo-1",
            spec_hint="other-spec",
        ) is False
        # hint 正常命中：front == verify-<hint> → verifier
        assert branch_shape_is_verifier(
            "fenix/verify-add-foo-1", "impl-verify-add-foo-1",
            spec_hint="add-foo",
        ) is True


class TestVerifyPrefixedSpecLockRelease:
    """事故主场景回归：verify- 开头 spec 的锁收尾释放。"""

    def test_cleanup_success_releases_implementer_lock(self, tmp_path):
        """cleanup(success=True) 必须释放 :implementer 锁（事故主场景）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        spec = "verify-dsh-plugins-live"

        wt = wm.create(spec, "implementer")
        assert wt is not None
        assert f"{spec}:implementer" in wm._spec_locks

        wm.cleanup(wt, success=True)
        assert f"{spec}:implementer" not in wm._spec_locks, (
            "verify- 开头 spec 名的 implementer 锁必须随 cleanup 释放"
            "（admin-global-1791999865：形状误判致锁泄漏 → 重派循环 → 冻结）"
        )

    def test_cleanup_failure_registers_implementer_legacy(self, tmp_path):
        """cleanup(success=False) 对 verify- 开头 spec 走实现族遗产登记路径。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        spec = "verify-dsh-plugins-live"

        wt = wm.create(spec, "implementer")
        assert wt is not None
        branch = wm.get_branch_name(wt)
        assert branch == f"fenix/{spec}-{branch.rsplit('-', 1)[-1]}"

        # 模拟半成品现场
        (wt / "wip.txt").write_text("WIP\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "[fenix] wip")

        wm.cleanup(wt, success=False)
        rec = wm._legacy.get(spec)
        assert rec is not None and rec.get("branch") == branch, (
            "死亡 implementer run（verify- 开头 spec 名）必须登记为遗产保留，"
            "而非被当作 verifier 失败走分支 -D"
        )
        assert Path(rec.get("path") or "") == Path(wt)
        assert f"{spec}:implementer" not in wm._spec_locks

    def test_keep_for_reuse_releases_non_verifier_family_lock(self, tmp_path):
        """keep_for_reuse 未传 agent_type 时按形状摘 non-verifier 族锁。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        spec = "verify-dsh-plugins-live"

        wt = wm.create(spec, "fast-track")
        assert wt is not None
        assert f"{spec}:fast-track" in wm._spec_locks

        wm.keep_for_reuse(spec, wt)
        assert f"{spec}:fast-track" not in wm._spec_locks, (
            "keep_for_reuse 收尾必须按实现族形状释放同族锁"
        )

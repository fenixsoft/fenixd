"""worktree 继承（fast-track 打回重派复用）单测。

覆盖 keep_for_reuse / create() 认领 / 继承语义 / 失效回退 / 宽限期回收：
  1. keep 后下轮 fast-track create 复用同一目录同一分支（含已提交成果继承）
  2. 复用遗产失效（目录被回收）→ 回退全新创建
  3. implementer 不参与复用（语义保持 implementer 自有遗产收编流程）
  4. reuse 遗产纳入宽限期兜底回收（复用 legacy 清扫机制）
  5. 成功收尾 cleanup 后认领痕迹清除（prompt 不再误注入继承说明）
基于真实 git 仓库 fixture（与 test_worktree_merge_guard 同构）。
"""

import subprocess
import time
from pathlib import Path

import pytest

from core.worktree_manager import WorktreeManager

from test_agent_runner import FakeLogger


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


def make_wm(root: Path) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger())


class TestWorktreeReuse:
    def test_keep_then_create_reuses_same_worktree(self, tmp_path):
        """keep 后下轮 fast-track create 认领同一目录同一分支，成果继承。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)

        wt1 = wm.create("demo", "fast-track")
        assert wt1 is not None
        branch1 = wm.get_branch_name(wt1)

        # 模拟 agent 在 worktree 内的实现成果（提交 + 未提交现场）
        (wt1 / "core" / "feat.py").parent.mkdir(parents=True, exist_ok=True)
        (wt1 / "core" / "feat.py").write_text("IMPL\n", encoding="utf-8")
        git(wt1, "add", "-A")
        git(wt1, "commit", "-q", "-m", "[fenix] demo: impl")
        (wt1 / "core" / "wip.py").write_text("WIP\n", encoding="utf-8")

        # 打回保留
        wm.keep_for_reuse("demo", wt1)
        assert wt1.exists(), "打回后目录必须保留"
        assert git(root, "rev-parse", "--verify", branch1).returncode == 0
        assert not [k for k in wm._spec_locks if k.startswith("demo")], "锁已释放"
        rec = wm.get_reuse_record("demo")
        assert rec is None or rec.get("path") == str(wt1)

        # 下轮派发：认领同一目录同一分支
        wt2 = wm.create("demo", "fast-track")
        assert wt2 is not None and Path(wt2) == Path(wt1)
        assert wm.get_branch_name(wt2) == branch1
        # 继承：已提交成果与未提交现场都在
        assert (wt2 / "core" / "feat.py").read_text(encoding="utf-8") == "IMPL\n"
        assert (wt2 / "core" / "wip.py").exists()

        # 成功收尾：cleanup 后目录移除（分支保留），认领痕迹清除
        wm.cleanup(wt2, success=True)
        assert not wt2.exists()
        assert wm.get_reuse_record("demo") is None

    def test_invalid_reuse_record_falls_back_to_fresh(self, tmp_path):
        """复用遗产已失效（目录被回收）→ 丢弃记录、回退全新创建。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)

        wt1 = wm.create("demo", "fast-track")
        branch1 = wm.get_branch_name(wt1)
        wm.keep_for_reuse("demo", wt1)
        # 模拟宽限期回收：目录与分支都被清掉
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force",
                        str(wt1)], capture_output=True)
        git(root, "branch", "-D", branch1)

        time.sleep(1.1)  # worktree 目录名含秒级时间戳，跨秒避免撞名干扰断言
        wt2 = wm.create("demo", "fast-track")
        assert wt2 is not None and Path(wt2) != Path(wt1), "失效遗产应回退新建"
        assert wm.get_reuse_record("demo") is None or \
            wm.get_reuse_record("demo").get("path") == str(wt2)

    def test_implementer_does_not_reuse(self, tmp_path):
        """复用仅限 fast-track；implementer 保持自有遗产收编语义。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)

        wt1 = wm.create("demo", "fast-track")
        wm.keep_for_reuse("demo", wt1)

        time.sleep(1.1)  # 跨秒避免 impl-<spec>-<ts> 目录名撞上保留中的旧目录
        wt2 = wm.create("demo", "implementer")
        assert wt2 is not None and Path(wt2) != Path(wt1)

    def test_reuse_record_reclaimed_after_grace(self, tmp_path):
        """reuse 遗产走 legacy 同一宽限期兜底回收，目录与分支一并清除。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)

        wt1 = wm.create("demo", "fast-track")
        branch1 = wm.get_branch_name(wt1)
        wm.keep_for_reuse("demo", wt1)

        reclaimed = wm._reclaim_expired_legacy(now=__import__("time").time() + 10_000)
        assert "demo" in reclaimed
        assert not wt1.exists()
        assert wm.get_reuse_record("demo") is None
        assert git(root, "rev-parse", "--verify", branch1, check=False).returncode != 0

    def test_keep_for_reuse_idempotent_across_redispatch_cycles(self, tmp_path):
        """打回→复用→再打回→再复用 循环稳定（覆盖式更新，不膨胀）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)

        for round_no in range(3):
            wt = wm.create("demo", "fast-track")
            assert wt is not None
            wm.keep_for_reuse("demo", wt)
            assert len(wm._legacy) == 1, "覆盖式更新，遗产链不膨胀"
            assert wt.exists()

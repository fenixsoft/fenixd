"""reclaim_stale_autostash 冲突条目防重试循环测试（fix-autostash-conflict-loop）。

复演生产事故（2026-09-07 指纹 a6fd0e29）：滞留 pre-dispatch autostash 条目引用
已废弃的 v3 布局，pop 恒冲突；旧实现 heal 后保留条目，周期巡检（fenixd.py 主循环
每 60s 调 reclaim_stale_autostash_if_idle）对同一栈顶条目原样重试 → 每分钟一条
ERROR 的无限循环，daemon 重启无效（状态在 git stash 栈，不在内存）。

修复语义：pop 冲突自愈（丢弃冲突方、保 HEAD，非冲突方改动已落工作区）后，核对
条目仍在栈顶且主树无 UU 残留，则 drop 该条目（sha 记入日志，gc 前可找回），
同一条目不再被重试。
"""

import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from core.worktree_manager import AUTOSTASH_MSG_PREFIX, WorktreeManager

from test_agent_runner import FakeLogger
from test_worktree_merge_guard import git, init_repo


def make_wm(root) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger())


def commit_file(root, path: str, content: str, msg: str) -> None:
    (root / path).write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", msg)


def stash_push_backdated(root, age_seconds: int) -> None:
    """以回拨的 committer 时间创建 fenix 前缀 stash 条目。新鲜度门
    （item 7b12cee6d0e0）按 committer 时间判龄，测试要走完回收链路须
    构造超过最小驻留龄的「滞留」条目。"""
    env = dict(os.environ)
    env["GIT_COMMITTER_DATE"] = (
        datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    ).strftime("%Y-%m-%dT%H:%M:%S %z")
    subprocess.run(
        ["git", "-C", str(root), "stash", "push", "-q", "-m", AUTOSTASH_MSG_PREFIX],
        env=env, check=True, capture_output=True, text=True,
    )


def make_conflicting_autostash(root, age_seconds: int | None = None) -> None:
    """构造「pop 必冲突」的 fenix 前缀滞留条目：工作区改动 stash 后，实现继续
    演进并提交同文件 → 栈顶条目 pop 时两侧同改 f.txt，确定性冲突。
    age_seconds 给定时以回拨 committer 时间创建条目（越过新鲜度门）。"""
    init_repo(root)
    commit_file(root, "f.txt", "ORIGIN", "[fenix] origin")
    (root / "f.txt").write_text("STASHED", encoding="utf-8")
    if age_seconds is None:
        git(root, "stash", "push", "-q", "-m", AUTOSTASH_MSG_PREFIX)
    else:
        stash_push_backdated(root, age_seconds)
    commit_file(root, "f.txt", "MERGED", "[fenix] merged implementation")
    assert git(root, "status", "--porcelain").stdout.strip() == ""
    assert AUTOSTASH_MSG_PREFIX in git(root, "stash", "list", "-n", "1").stdout


class TestReclaimStaleAutostash:
    # 超过新鲜度门（_AUTOSTASH_RECLAIM_MIN_AGE_SECONDS=300）的回拨量
    STALE_AGE_SECONDS = 600

    def test_fresh_entry_not_reclaimed(self, tmp_path):
        """新鲜度门（item 7b12cee6d0e0）：低于最小驻留龄的 fenix 条目不回收
        ——防跨进程 dashboard merge-back 的 stash→merge 窗口内把在飞条目当
        滞留条目 pop+drop。条目保留交下轮巡检。"""
        make_conflicting_autostash(tmp_path)  # 条目 committer 时间即当前
        wm = make_wm(tmp_path)
        assert wm.reclaim_stale_autostash() is False
        assert AUTOSTASH_MSG_PREFIX in git(tmp_path, "stash", "list").stdout

    def test_conflicted_reclaim_drops_entry_after_heal(self, tmp_path):
        """pop 冲突自愈后条目必须被 drop——否则周期巡检无限重试同一栈顶条目。"""
        make_conflicting_autostash(tmp_path, age_seconds=self.STALE_AGE_SECONDS)
        wm = make_wm(tmp_path)
        assert wm.reclaim_stale_autostash() is False
        # 关键断言：fenix 条目已不在栈中，下一 tick 不再重试
        assert AUTOSTASH_MSG_PREFIX not in git(tmp_path, "stash", "list").stdout
        # 主树回到干净可写，内容为已合并实现（自愈保 HEAD 语义不变）
        assert git(tmp_path, "status", "--porcelain").stdout.strip() == ""
        assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "MERGED"

    def test_clean_reclaim_still_pops(self, tmp_path):
        """无冲突路径回归：干净主树上滞留 autostash 正常恢复且条目被消费。"""
        init_repo(tmp_path)
        commit_file(tmp_path, "f.txt", "ORIGIN", "[fenix] origin")
        (tmp_path / "f.txt").write_text("USERWORK", encoding="utf-8")
        stash_push_backdated(tmp_path, self.STALE_AGE_SECONDS)
        wm = make_wm(tmp_path)
        assert wm.reclaim_stale_autostash() is True
        assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "USERWORK"
        assert git(tmp_path, "stash", "list").stdout.strip() == ""

    def test_dirty_tree_skips_reclaim(self, tmp_path):
        """主树 tracked 脏（用户工作中）不抢：条目原样保留。"""
        make_conflicting_autostash(tmp_path)
        # 「脏」按 tracked-only 口径判定（autostash 只装 tracked 修改），
        # 须改动已跟踪文件才构成用户工作中的现场
        (tmp_path / "f.txt").write_text("USER WIP\n", encoding="utf-8")
        wm = make_wm(tmp_path)
        assert wm.reclaim_stale_autostash() is False
        assert AUTOSTASH_MSG_PREFIX in git(tmp_path, "stash", "list").stdout
        assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "USER WIP\n"

    def test_untracked_only_tree_no_longer_blocks_reclaim(self, tmp_path):
        """纯 untracked 文件不算脏（fix 口径）：不再卡死巡检，冲突条目照常自愈消费。"""
        make_conflicting_autostash(tmp_path, age_seconds=self.STALE_AGE_SECONDS)
        (tmp_path / "other.txt").write_text("wip\n", encoding="utf-8")
        wm = make_wm(tmp_path)
        assert wm.reclaim_stale_autostash() is False
        # pop 冲突自愈保 HEAD 后条目被 drop，下一 tick 不再重试
        assert AUTOSTASH_MSG_PREFIX not in git(tmp_path, "stash", "list").stdout
        assert git(tmp_path, "status", "--porcelain").stdout.strip() == "?? other.txt"
        assert (tmp_path / "other.txt").read_text(encoding="utf-8") == "wip\n"
        assert (tmp_path / "f.txt").read_text(encoding="utf-8") == "MERGED"

    def test_non_fenix_stash_never_touched(self, tmp_path):
        """人工手工 stash（无 fenix 前缀）永不自动回收。"""
        init_repo(tmp_path)
        commit_file(tmp_path, "f.txt", "ORIGIN", "[fenix] origin")
        (tmp_path / "f.txt").write_text("MANUAL", encoding="utf-8")
        git(tmp_path, "stash", "push", "-q", "-m", "my own stash")
        wm = make_wm(tmp_path)
        assert wm.reclaim_stale_autostash() is False
        assert "my own stash" in git(tmp_path, "stash", "list").stdout

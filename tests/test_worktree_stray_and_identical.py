"""2026-09-02 add-fast-track-mode merge-back 死锁复盘的四处框架修复测试。

覆盖：
  1. _pgrep_spec_process 锚定 claude 进程：cmdline 含 worktree 路径的非 agent
     进程（v2 dev-server 孤儿）不再被当成持锁者，claude 进程仍能命中
  2. _kill_worktree_strays：清扫杀掉残留测试子进程，claude 进程豁免
  3. _discard_identical_local_changes：merge 需写路径上的 tracked 本地修改与
     分支内容字节级一致时丢弃并重试 merge；不一致（含混合）时保守放弃、
     不动任何文件
  4. ensure_clean_tree 脏检测看 porcelain XY 状态位（[0]/[1]），未暂存修改
     能触发 autostash——merge-back 不再被主树脏 tracked 文件死锁；pop 冲突
     由 restore_after_merge 自愈（保留 merge 结果、stash 条目可找回）

死锁链（复演目标）：主树遗留与分支字节级相同的 tracked 修改 → 旧脏检测恒
False 未 stash → merge 被拒 → self-heal 只认 ignored 草稿 → 失败；重派又被
dev-server 孤儿骗过存活检测永久 skip。
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.worktree_manager import WorktreeManager, _is_claude_process

from test_agent_runner import FakeLogger
from test_worktree_merge_guard import git, init_repo

FAKE_SLEEP = "import time; time.sleep(20)"


def make_wm(root: Path) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger())


def spawn_proc(token: str, fake_argv0: str) -> subprocess.Popen:
    """spawn 一个 20s 进程：cmdline 含 token，argv[0] 伪装为 fake_argv0。

    经 execv 重建 argv 以精确控制 argv[0]（pgrep -f 按整条 cmdline 匹配，
    _is_claude_process 按 argv[0] basename 判定）。
    """
    launcher = "import os, sys\nos.execv(sys.argv[1], [sys.argv[2]] + sys.argv[3:])\n"
    return subprocess.Popen(
        [sys.executable, "-c", launcher, sys.executable, fake_argv0,
         "-c", FAKE_SLEEP, token],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def wait_token_in_pgrep(token: str, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = subprocess.run(["pgrep", "-f", token],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return True
        time.sleep(0.05)
    return False


def make_tracked_file_branch(root: Path, branch: str, path: str,
                             base_content: str, branch_content: str) -> str:
    """建 tracked 文件并派生修改分支：base 提交 base_content，分支改 branch_content，
    最后 checkout 回 base（工作区=base 版，等待测试写入本地修改）。返回 base sha。"""
    root.mkdir(parents=True, exist_ok=True)
    base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
    git(root, "checkout", "-q", "-b", branch)
    (root / path).write_text(branch_content, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"[fenix] branch {branch} modify {path}")
    git(root, "checkout", "-q", base_sha)
    return base_sha


class TestPgrepAnchoring:
    def test_non_claude_process_does_not_hold_lock(self, tmp_path):
        """dev-server 型孤儿（argv0 非 claude）即使 cmdline 含 worktree 路径也不算持锁。"""
        spec = f"pgrepnonclaude{os.getpid()}"
        token = f"worktrees/impl-{spec}-1"
        proc = spawn_proc(token, "node")
        try:
            assert wait_token_in_pgrep(token), "测试进程应能被 pgrep 扫到"
            wm = make_wm(tmp_path)
            assert wm._pgrep_spec_process(spec) is False
        finally:
            proc.kill()
            proc.wait()

    def test_claude_process_holds_lock(self, tmp_path):
        """argv0 为 claude 的进程即使内容是伪装脚本也照常命中（锚定语义不误杀）。"""
        spec = f"pgrepclaude{os.getpid()}"
        token = f"worktrees/impl-{spec}-1"
        proc = spawn_proc(token, "claude")
        try:
            assert wait_token_in_pgrep(token), "测试进程应能被 pgrep 扫到"
            wm = make_wm(tmp_path)
            assert wm._pgrep_spec_process(spec) is True
        finally:
            proc.kill()
            proc.wait()


class TestKillStrays:
    def test_kills_non_claude_stray(self, tmp_path):
        """收工清扫杀掉 cmdline 引用 worktree 的非 agent 进程。"""
        name = f"impl-straykill-{os.getpid()}"
        token = f"worktrees/{name}"
        proc = spawn_proc(token, "node")
        try:
            assert wait_token_in_pgrep(token)
            wm = make_wm(tmp_path)
            killed = wm._kill_worktree_strays(name)
            assert proc.pid in killed
            assert proc.wait(timeout=10) is not None
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

    def test_spares_claude_process(self, tmp_path):
        """清扫豁免 claude 进程（防误杀在跑的 attempt）。"""
        name = f"impl-strayspare-{os.getpid()}"
        token = f"worktrees/{name}"
        proc = spawn_proc(token, "claude")
        try:
            assert wait_token_in_pgrep(token)
            wm = make_wm(tmp_path)
            assert wm._kill_worktree_strays(name) == []
            assert proc.poll() is None, "claude 进程不应被清扫"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


class TestDiscardIdenticalLocalChanges:
    """merge 级场景（脏检测修复后 autostash 生效，走 stash→merge→pop 主路径，
    identical self-heal 退为 stash/merge 竞态窗口的纵深防御）+ 单元级直测。"""

    @pytest.fixture()
    def repo(self, tmp_path):
        root = tmp_path / "repo"
        init_repo(root)
        for name in ("skill.md", "a.md", "b.md"):
            (root / name).write_text("OLD\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] add files")
        return root

    def test_identical_copy_is_discarded_and_merged(self, repo):
        """主树副本与分支字节级一致 → merge 成功、内容为分支版、路径干净、无冲突。"""
        make_tracked_file_branch(repo, "fenix/impl-identical", "skill.md",
                                 "OLD\n", "NEW\n")
        # 主树留一份与分支相同的未提交修改（implementer 副本污染形态）
        (repo / "skill.md").write_text("NEW\n", encoding="utf-8")

        wm = make_wm(repo)
        success, err = wm.merge_back_from_branch("fenix/impl-identical")
        assert success, f"merge 应经 autostash 成功，实际失败: {err}"
        assert (repo / "skill.md").read_text(encoding="utf-8") == "NEW\n"
        status = git(repo, "status", "--porcelain").stdout
        assert "skill.md" not in status, "merge 后该路径应干净"
        assert wm.last_stash_pop_conflicts == [], "一致副本不应产生 pop 冲突"

    def test_divergent_copy_unblocks_via_stash_selfheal(self, repo):
        """分歧本地修改 → autostash 生效后 merge 不再死锁：分支结果胜出，
        pop 冲突自愈丢弃 stash 侧改动，stash 条目保留可找回。"""
        make_tracked_file_branch(repo, "fenix/impl-divergent", "skill.md",
                                 "OLD\n", "NEW\n")
        (repo / "skill.md").write_text("LOCAL\n", encoding="utf-8")

        wm = make_wm(repo)
        success, err = wm.merge_back_from_branch("fenix/impl-divergent")
        assert success, f"merge 应在 autostash+pop 自愈下成功，实际失败: {err}"
        assert (repo / "skill.md").read_text(encoding="utf-8") == "NEW\n"
        assert wm.last_stash_pop_conflicts == ["skill.md"]
        stash_list = git(repo, "stash", "list").stdout.strip()
        assert stash_list, "被自愈丢弃的本地改动应保留在 stash 中可找回"
        stash_show = git(repo, "stash", "show", "-p", "stash@{0}").stdout
        assert "LOCAL\n" in stash_show, "stash 中应能找回分歧的本地内容"

    def test_mixed_blockers_branch_wins_conflicted_file_recorded(self, repo):
        """混合修改（一份与分支一致、一份分歧）→ merge 成功，分歧文件以分支
        版本落地并记入 pop 冲突清单，一致文件干净合入。"""
        git(repo, "checkout", "-q", "-b", "fenix/impl-mixed")
        (repo / "a.md").write_text("NEW\n", encoding="utf-8")
        (repo / "b.md").write_text("BRANCH\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "[fenix] branch modify a+b")
        base_sha = git(repo, "rev-parse", "HEAD~1").stdout.strip()
        git(repo, "checkout", "-q", base_sha)
        # a.md 与分支一致；b.md 分歧（两者均为 tracked 未暂存修改）
        (repo / "a.md").write_text("NEW\n", encoding="utf-8")
        (repo / "b.md").write_text("LOCAL\n", encoding="utf-8")

        wm = make_wm(repo)
        success, err = wm.merge_back_from_branch("fenix/impl-mixed")
        assert success, f"merge 应在 autostash+pop 自愈下成功，实际失败: {err}"
        assert (repo / "a.md").read_text(encoding="utf-8") == "NEW\n"
        assert (repo / "b.md").read_text(encoding="utf-8") == "BRANCH\n"
        assert wm.last_stash_pop_conflicts == ["b.md"]

    # ── 单元级直测：identical self-heal（纵深防御路径） ──────────────────────

    def test_heal_unit_discards_identical_and_backs_up(self, repo):
        """字节级一致 → 恢复 HEAD 版 + 备份保留原内容，返回 True。"""
        make_tracked_file_branch(repo, "fenix/impl-unit-ident", "skill.md",
                                 "OLD\n", "NEW\n")
        (repo / "skill.md").write_text("NEW\n", encoding="utf-8")

        wm = make_wm(repo)
        assert wm._discard_identical_local_changes(
            ["skill.md"], "fenix/impl-unit-ident") is True
        assert (repo / "skill.md").read_text(encoding="utf-8") == "OLD\n"
        backups = list((repo / ".fenix" / "merge-backup").glob("identical-*"))
        assert len(backups) == 1
        assert (backups[0] / "skill.md").read_text(encoding="utf-8") == "NEW\n"

    def test_heal_unit_refuses_divergent_untouched(self, repo):
        """内容与分支不一致 → 返回 False、文件原样保留（疑似真实本地工作）。"""
        make_tracked_file_branch(repo, "fenix/impl-unit-divergent", "skill.md",
                                 "OLD\n", "NEW\n")
        (repo / "skill.md").write_text("LOCAL\n", encoding="utf-8")

        wm = make_wm(repo)
        assert wm._discard_identical_local_changes(
            ["skill.md"], "fenix/impl-unit-divergent") is False
        assert (repo / "skill.md").read_text(encoding="utf-8") == "LOCAL\n"

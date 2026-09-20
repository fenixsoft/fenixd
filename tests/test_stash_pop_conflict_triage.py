"""evo-stash-pop-conflict-triage 三态重试测试。

覆盖 spec/changes/evo-stash-pop-conflict-triage 的 tasks 2.1-2.4：

  2.1 纯文本同 hunk 冲突 → 态 2 恢复 commit 落盘，stash 版内容（LOCAL\\n）在
      恢复提交（HEAD）中可见；stash 条目保留；不出现「静默丢弃」。
  2.2 二进制冲突（d.bin）→ 态 2 经 --theirs 取回 stash 版字节内容，恢复 commit
      中该文件与 stash 版字节级一致（回归「读工作区标记失败」取证盲区——pop 后
      工作区为 merge 结果、无冲突标记）。
  2.3 路径作用域——调用前在 index 预置另一个 staged 修改（git add -- other.ts），
      态 2 恢复 commit 后该条目仍在 index、内容未被吞并，且主树 porcelain 非空
      属预期。
  2.4 兜底路径——态 2 的 git commit 注入失败时，stash 版内容仍在工作区且
      disposition 已登记（mode=3），无静默丢弃。

全部基于真实 git 仓库 fixture（与 test_worktree_merge_guard 同款 git/init_repo
助手）：分支改 shared.py → 主树 WIP 冲突改动 autostash → merge → restore_after_merge
触发 pop 冲突三态自愈。
"""

import subprocess

from core.worktree_manager import AUTOSTASH_MSG_PREFIX

from test_worktree_merge_guard import git, init_repo, make_wm


def make_conflicted_repo(root, wip_content="LOCAL\n"):
    """构造「pop 必冲突」现场：分支改 shared.py → 主树 WIP 冲突 → autostash → merge。

    WIP 与分支版在 base 同 hunk 上分歧，pop 确定性冲突。返回 (wm, stash_sha)。
    """
    init_repo(root)  # shared.py = "BASE\n"
    base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
    git(root, "checkout", "-q", "-b", "fenix/impl")
    (root / "shared.py").write_text("MERGED\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] branch modifies shared.py")
    git(root, "checkout", "-q", base_sha)
    (root / "shared.py").write_text(wip_content, encoding="utf-8")
    wm = make_wm(root)
    assert wm.ensure_clean_tree() is True
    sha = git(root, "rev-parse", "--verify", "stash@{0}").stdout.strip()
    git(root, "merge", "--no-ff", "fenix/impl", "-m", "[fenix] merge impl")
    return wm, sha


class TestStashPopConflictTriage:
    # ── 2.1：纯文本同 hunk 冲突 → 态 2 恢复 commit 落盘 ─────────────────────────

    def test_state2_recovery_commit_restores_stash_content(self, tmp_path):
        """同 hunk 冲突走态 2：stash 版内容（LOCAL\\n）在恢复提交中可见，条目保留。"""
        root = tmp_path / "repo"
        wm, sha = make_conflicted_repo(root)

        ok, conflict_files = wm.restore_after_merge()
        assert ok is True
        assert conflict_files == ["shared.py"], f"应检出 UU 冲突文件: {conflict_files}"
        # 态 2 恢复 commit 落盘：stash 版内容在恢复提交（HEAD）中可见
        assert git(root, "show", "HEAD:shared.py").stdout == "LOCAL\n"
        # 工作区为 stash 版内容（不再「分支版胜出」丢弃本地改动）
        assert (root / "shared.py").read_text(encoding="utf-8") == "LOCAL\n"
        # 主树不再处于半合并态：无 UU 残留
        assert not git(root, "ls-files", "-u").stdout.strip()
        # stash 条目保留
        lst = git(root, "stash", "list")
        assert AUTOSTASH_MSG_PREFIX in lst.stdout, f"条目应保留: {lst.stdout!r}"
        # 不出现「静默丢弃」：三态处置日志登记 mode=2，无 auto-dropped
        triage = [w for w in wm.logger.warnings if "mode=2" in w and "triage" in w]
        assert triage, f"应记录三态处置日志: {wm.logger.warnings}"
        assert not [w for w in wm.logger.warnings if "auto-dropped" in w]
        # 条目去向记账：保留 + 钉住 sha
        assert wm.last_stash_entry_fate == {"kept": True, "sha": sha}

    # ── 2.2：二进制冲突 → 态 2 --theirs 字节级恢复 ─────────────────────────────

    def test_state2_theirs_recovers_binary_bytes(self, tmp_path):
        """二进制冲突走态 2：--theirs 取回 stash 版字节，恢复 commit 字节级一致。"""
        root = tmp_path / "repo"
        init_repo(root)
        (root / "d.bin").write_bytes(b"SEG\x00TAIL")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] base with binary")
        base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "d.bin").write_bytes(b"BRANCH1\x00SEG\x00TAIL")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch binary")
        git(root, "checkout", "-q", base_sha)
        (root / "d.bin").write_bytes(b"LOCAL1\x00SEG\x00TAIL")
        wm = make_wm(root)
        assert wm.ensure_clean_tree() is True
        sha = git(root, "rev-parse", "--verify", "stash@{0}").stdout.strip()
        git(root, "merge", "--no-ff", "fenix/impl", "-m", "[fenix] merge impl")

        ok, conflict_files = wm.restore_after_merge()
        assert ok is True
        assert conflict_files == ["d.bin"], f"应检出 UU 冲突文件: {conflict_files}"
        # 态 2 --theirs 取回 stash 版字节内容（pop 后工作区为 merge 结果、无标记）
        stash_blob = git(root, "rev-parse", f"{sha}:d.bin").stdout.strip()
        assert (root / "d.bin").read_bytes() == b"LOCAL1\x00SEG\x00TAIL"
        # 恢复 commit 中该文件与 stash 版字节级一致
        head_blob = git(root, "rev-parse", "HEAD:d.bin").stdout.strip()
        assert head_blob == stash_blob, "恢复 commit 应与 stash 版字节级一致"
        assert (
            subprocess.run(
                ["git", "-C", str(root), "show", "HEAD:d.bin"], capture_output=True
            ).stdout
            == b"LOCAL1\x00SEG\x00TAIL"
        )
        # stash 条目保留
        assert AUTOSTASH_MSG_PREFIX in git(root, "stash", "list").stdout

    # ── 2.3：路径作用域——恢复 commit 不吞并 index 其余 staged 条目 ────────────

    def test_path_scope_preserves_other_staged_entries(self, tmp_path):
        """态 2 恢复 commit 只含冲突路径：other.ts 仍在 index、内容未被吞并。"""
        root = tmp_path / "repo"
        init_repo(root)
        (root / "other.ts").write_text("BASE-OTHER\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] base with other.ts")
        base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
        git(root, "checkout", "-q", "-b", "fenix/impl")
        (root / "shared.py").write_text("MERGED\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] branch modifies shared.py")
        git(root, "checkout", "-q", base_sha)
        # 主树 WIP：shared.py 冲突改动 + other.ts 预置 staged 修改
        (root / "shared.py").write_text("LOCAL\n", encoding="utf-8")
        (root / "other.ts").write_text("WIP-OTHER\n", encoding="utf-8")
        git(root, "add", "--", "other.ts")
        wm = make_wm(root)
        assert wm.ensure_clean_tree() is True
        git(root, "merge", "--no-ff", "fenix/impl", "-m", "[fenix] merge impl")

        ok, conflict_files = wm.restore_after_merge()
        assert ok is True
        assert conflict_files == ["shared.py"], f"应只检出 shared.py: {conflict_files}"
        # 路径作用域：恢复 commit 只含冲突路径 shared.py，HEAD:other.ts 未变
        assert git(root, "show", "HEAD:shared.py").stdout == "LOCAL\n"
        assert git(root, "show", "HEAD:other.ts").stdout == "BASE-OTHER\n"
        # other.ts 条目仍在 index、内容未被吞并
        staged = git(root, "diff", "--cached", "--name-only").stdout.strip()
        assert "other.ts" in staged, f"other.ts 应仍在 index: {staged!r}"
        assert git(root, "show", ":other.ts").stdout == "WIP-OTHER\n"
        assert (root / "other.ts").read_text(encoding="utf-8") == "WIP-OTHER\n"
        # 主树 porcelain 非空属预期（other.ts 仍 staged）
        assert git(root, "status", "--porcelain").stdout.strip()

    # ── 2.4：兜底路径——态 2 commit 注入失败 ──────────────────────────────────

    def test_state3_fallback_on_commit_failure(self, tmp_path, monkeypatch):
        """态 2 的 git commit 注入失败 → 态 3 兜底：内容仍在工作区、disposition 已登记。"""
        root = tmp_path / "repo"
        wm, sha = make_conflicted_repo(root)

        import core.worktree_manager as twm

        orig_run = twm.subprocess.run

        def fake_run(cmd, **kw):
            if "commit" in cmd:
                class R:
                    returncode = 1
                    stdout = ""
                    stderr = "boom (injected commit failure)"

                return R()
            return orig_run(cmd, **kw)

        monkeypatch.setattr(twm.subprocess, "run", fake_run)

        ok, conflict_files = wm.restore_after_merge()
        assert ok is True
        assert conflict_files == ["shared.py"]
        # stash 版内容仍在工作区（--theirs 已落盘，commit 注入失败也不丢）
        assert (root / "shared.py").read_text(encoding="utf-8") == "LOCAL\n"
        # 兜底 disposition 已登记（mode=3 结构化日志）
        triage = [w for w in wm.logger.warnings if "mode=3" in w and "triage" in w]
        assert triage, f"应登记态 3 兜底 disposition: {wm.logger.warnings}"
        # stash 条目保留 + 去向记账
        assert AUTOSTASH_MSG_PREFIX in git(root, "stash", "list").stdout
        assert wm.last_stash_entry_fate == {"kept": True, "sha": sha}
        # 无静默丢弃：无 auto-dropped 日志
        assert not [w for w in wm.logger.warnings if "auto-dropped" in w]

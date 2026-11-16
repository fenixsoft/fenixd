"""tests/test_impl_delivery_preservation.py — 实现交付保全真引用（evo-impl-worktree-preservation-refs）。

覆盖 tasks 3.1 六场景：
1. 清扫后 refs/preservation/<run_id> 存在且交付链 for-each-ref --contains 可达；
2. update-ref 失败回退现状行为并升 ERROR；
3. 冻结在途（blocked+frozen+_frozen_hold）不删引用；
4. 终态消费（done）后宽限期清理引用；
5. untracked 文件经引用链检出（含 untracked-only WIP：stash create 空产出形态）；
6. clean worktree 引用指向分支 tip、分支删除后链可达。

附：就位校验三态（覆盖 tip / 缺失补写 / 陈旧不覆盖）、update-ref 幂等重扫覆盖。
真实 git 仓库 + 真实 WorktreeManager，全程不经 mock（与 test_branch_gc 同款基建）。
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.worktree_manager import WorktreeManager


# ── 本地测试基建（与 test_branch_gc / test_interrupt_recovery_preserve 同款形态） ──


class FakeLogger:
    def __init__(self):
        self.records: list = []

    def _rec(self, level, component, msg):
        self.records.append((level, component, msg))

    def info(self, component, msg, context=None):
        self._rec("info", component, msg)

    def warning(self, component, msg, context=None):
        self._rec("warning", component, msg)

    def error(self, component, msg, context=None):
        self._rec("error", component, msg)


def git(root: Path, *args, check=True, env_extra=None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, env=env,
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


def backdated(root: Path, days_ago: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S %z")


def commit_file(root: Path, rel: str, content: str, msg: str, date: str | None = None):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    env_extra = {}
    if date:
        env_extra["GIT_AUTHOR_DATE"] = date
        env_extra["GIT_COMMITTER_DATE"] = date
    git(root, "commit", "-q", "-m", msg, env_extra=env_extra)


def merged_branch(root: Path, branch: str, days_ago: float) -> None:
    """从 main 建分支、回拨时间提交并 ff 合并回 main（--merged 口径成立）。"""
    git(root, "checkout", "-q", "main")
    git(root, "checkout", "-q", "-b", branch)
    commit_file(root, "feat.py", f"{branch}\n", f"[fenix] {branch}",
                date=backdated(root, days_ago))
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "--ff-only", branch)


def make_wm(root: Path, logger=None) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(
        base, root, logger or FakeLogger(),
        process_scanner=lambda spec: False,
    )


def make_state(root: Path, specs: dict) -> None:
    from core.state_machine import StateMachine
    state_path = root / ".fenix" / "STATE.md"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    sm = StateMachine(state_path, FakeLogger())
    for name, entry in specs.items():
        sm.add_spec(name, entry)


def preservation_refs(root: Path) -> set:
    res = git(root, "for-each-ref", "--format=%(refname)", "refs/preservation/")
    return {ln.strip() for ln in res.stdout.splitlines() if ln.strip()}


def backdate_ref(root: Path, ref: str, days_ago: float) -> None:
    """把 loose ref 文件 mtime 回拨（ref GC 宽限期时钟 = 引用写入时刻）。"""
    run_id = ref.split("refs/preservation/", 1)[1]
    ref_file = root / ".git" / "refs" / "preservation" / run_id
    old = time.time() - days_ago * 86400
    os.utime(ref_file, (old, old))


# ── 场景 1：清扫后 refs/preservation/<run_id> 存在且交付链 --contains 可达 ────


class TestCleanupPreservesRef:
    def test_s1_failed_cleanup_ref_reachable_and_contains_tip(self, tmp_path):
        """verifier 失败清扫（worktree remove --force + branch -D）后，快照引用
        覆盖清扫前分支 tip，untracked/tracked WIP 内容经引用链均可检出。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("presdemo", "verifier")
        branch = wm.get_branch_name(wt)
        run_id = branch[len("fenix/"):]
        # 已提交交付 + tracked 改动 + untracked 新增（快照须全含）
        (wt / "delivery.py").write_text("DELIVERY v1\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "[fenix] presdemo: impl")
        pre_tip = git(wt, "rev-parse", "HEAD").stdout.strip()
        (wt / "shared.py").write_text("DIRTY\n", encoding="utf-8")
        (wt / "wip_untracked.txt").write_text("precious wip\n", encoding="utf-8")

        wm.cleanup(wt, success=False)

        # worktree 已删、分支已删（既有 --force 失败清扫口径）
        assert not wt.exists(), "worktree 目录应被清扫"
        names = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/").stdout
        assert branch not in names, "失败清扫应删除 verifier 分支"
        # 快照引用就位：存在、指向 commit、覆盖清扫前分支 tip（--contains 口径）
        ref = f"refs/preservation/{run_id}"
        assert ref in preservation_refs(root), "preservation 引用未就位"
        ref_sha = git(root, "rev-parse", "--verify", ref).stdout.strip()
        assert git(root, "cat-file", "-t", ref_sha).stdout.strip() == "commit"
        lst = git(root, "for-each-ref", f"--contains={pre_tip}",
                  "--format=%(refname)", "refs/preservation/").stdout
        assert ref in lst, f"引用未覆盖分支 tip: {lst!r}"
        # 交付链内容可检出：已提交交付（parent 链）+ tracked WIP + untracked WIP
        hist = git(root, "log", "--format=%s", f"{ref_sha}").stdout
        assert "[fenix] presdemo: impl" in hist, "已提交交付应经引用链可达"
        assert git(root, "show", f"{ref}:shared.py").stdout == "DIRTY\n"
        assert git(root, "show", f"{ref}:wip_untracked.txt").stdout == "precious wip\n"

    def test_snapshot_ref_idempotent_overwrite(self, tmp_path):
        """update-ref 幂等：重扫（二次快照）覆盖同一引用到最新快照。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("idempot", "implementer")
        branch = wm.get_branch_name(wt)
        run_id = branch[len("fenix/"):]
        (wt / "shared.py").write_text("V1\n", encoding="utf-8")
        (wt / "u1.txt").write_text("one\n", encoding="utf-8")
        sha1 = wm._snapshot_dirty_worktree(wt, branch)
        ref = f"refs/preservation/{run_id}"
        assert git(root, "rev-parse", "--verify", ref).stdout.strip() == sha1
        (wt / "shared.py").write_text("V2\n", encoding="utf-8")
        (wt / "u2.txt").write_text("two\n", encoding="utf-8")
        sha2 = wm._snapshot_dirty_worktree(wt, branch)
        assert sha2 != sha1, "二次快照应产出新 preservation commit"
        assert git(root, "rev-parse", "--verify", ref).stdout.strip() == sha2, \
            "引用应被幂等覆盖到最新快照"
        assert git(root, "show", f"{ref}:u2.txt").stdout == "two\n"
        assert git(root, "show", f"{ref}:u1.txt").stdout == "one\n"


# ── 场景 2：update-ref 失败回退现状行为并升 ERROR ────────────────────────────


class TestRefWriteFailureFallback:
    def test_s2_update_ref_failure_falls_back_with_error(self, tmp_path):
        """引用锁文件占位使 update-ref 确定性失败：返回悬空 stash sha、
        ERROR 级留痕且指引回退为 git stash store 形态。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("faildemo", "implementer")
        branch = wm.get_branch_name(wt)
        run_id = branch[len("fenix/"):]
        (wt / "shared.py").write_text("DIRTY\n", encoding="utf-8")
        (wt / "wip_new.txt").write_text("wip\n", encoding="utf-8")
        # 陈旧引用锁：git update-ref cannot lock ref（真实失败路径，非 mock）
        lock = root / ".git" / "refs" / "preservation" / f"{run_id}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("", encoding="utf-8")

        sha = wm._snapshot_dirty_worktree(wt, branch)

        assert sha, "引用写入失败须回退现状行为：返回悬空 stash commit SHA"
        assert git(root, "rev-parse", "--verify", sha, check=False).returncode == 0, \
            "回退 SHA 须是对象库中的有效 commit"
        assert f"refs/preservation/{run_id}" not in preservation_refs(root), \
            "写入失败不应残留引用"
        errs = [m for lv, _c, m in wm.logger.records if lv == "error"]
        assert any(
            "Pre-rmtree preservation ref write FAILED" in m and "git stash store" in m
            for m in errs
        ), f"回退路径缺 ERROR 级 stash store 指引: {errs}"
        lock.unlink()


# ── 场景 3/4：引用生命周期（冻结在途豁免 / 终态消费后清理） ──────────────────


class TestRefLifecycleOnSweep:
    def _gc_setup(self, tmp_path):
        root = tmp_path / "repo"
        init_repo(root)
        return root, make_wm(root)

    def test_s3_frozen_in_flight_keeps_ref_and_branch(self, tmp_path):
        """冻结待人工裁决在途（blocked+frozen+_frozen_hold）：分支与引用均不删，
        引用已超宽限期仍保留（豁免来自守卫链而非宽限期未到）。"""
        root, wm = self._gc_setup(tmp_path)
        branch = "fenix/frozenkeeper-1009"
        merged_branch(root, branch, days_ago=30)
        tip = git(root, "rev-parse", branch).stdout.strip()
        ref = "refs/preservation/frozenkeeper-1009"
        git(root, "update-ref", ref, tip)
        backdate_ref(root, ref, days_ago=30)
        make_state(root, {"frozenkeeper": {
            "status": "blocked", "frozen": True, "_frozen_hold": True,
        }})

        stats = wm._gc_merged_branches()

        names = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/").stdout
        assert branch in names, "冻结在途分支必须保留"
        assert ref in preservation_refs(root), "冻结在途引用 MUST NOT 删除"
        assert stats["deleted"] == []
        assert stats["preservation_deleted"] == []
        assert stats["preservation_frozen"] == 1, \
            f"冻结豁免计数缺失（宽限期已过仍保留应归因冻结）: {stats}"

    def test_s4_terminal_consumption_deletes_ref_after_grace(self, tmp_path):
        """终态（done：merge-back 决策完成留痕）+ 引用写入时刻超宽限期 →
        分支与引用同轮回收，仓库不留长期悬挂引用。"""
        root, wm = self._gc_setup(tmp_path)
        branch = "fenix/donepres-1010"
        merged_branch(root, branch, days_ago=30)
        tip = git(root, "rev-parse", branch).stdout.strip()
        ref = "refs/preservation/donepres-1010"
        git(root, "update-ref", ref, tip)
        backdate_ref(root, ref, days_ago=30)
        make_state(root, {"donepres": {"status": "done"}})

        stats = wm._gc_merged_branches()

        assert stats["deleted"] == [branch], "终态 spec 超期分支应回收"
        assert stats["preservation_deleted"] == [ref], \
            f"终态超期引用应同轮清理: {stats}"
        assert ref not in preservation_refs(root)
        # 宽限期内（写入时刻新鲜）的终态引用保留：刚就位的引用至少存活一个宽限期
        ref_fresh = "refs/preservation/donefresh-1011"
        fresh_branch = "fenix/donefresh-1011"
        merged_branch(root, fresh_branch, days_ago=30)
        git(root, "update-ref", ref_fresh, git(root, "rev-parse", fresh_branch).stdout.strip())
        stats2 = wm._gc_merged_branches()
        assert stats2["preservation_deleted"] == [], "宽限期内引用不得删除"
        assert ref_fresh in preservation_refs(root)

    def test_preservation_ref_readiness_gate(self, tmp_path):
        """就位校验三态：覆盖 tip 放行 / 缺失就地补写 / 陈旧不覆盖保守保留。"""
        root, wm = self._gc_setup(tmp_path)
        branch = "fenix/gatekeeper-1012"
        merged_branch(root, branch, days_ago=30)
        tip = git(root, "rev-parse", branch).stdout.strip()
        ref = "refs/preservation/gatekeeper-1012"
        # 缺失 → 就地补写（自愈）
        ok, reason = wm._ensure_preservation_ref_for_branch(branch)
        assert ok, f"缺失引用应就地补写: {reason}"
        assert git(root, "rev-parse", "--verify", ref).stdout.strip() == tip
        # 已覆盖 tip → 放行（不重写、mtime 不动）
        before = (root / ".git" / "refs" / "preservation" / "gatekeeper-1012").stat().st_mtime
        time.sleep(0.01)
        ok2, _ = wm._ensure_preservation_ref_for_branch(branch)
        assert ok2
        after = (root / ".git" / "refs" / "preservation" / "gatekeeper-1012").stat().st_mtime
        assert after == before, "已就位引用不得重写"
        # 已存在但不含 tip（陈旧快照）→ 保守保留语义，且不孤儿化既有快照
        stale_commit = git(root, "commit-tree", f"{tip}^{{tree}}", "-m", "stale").stdout.strip()
        git(root, "update-ref", ref, stale_commit)
        ok3, reason3 = wm._ensure_preservation_ref_for_branch(branch)
        assert not ok3, "陈旧引用（不含 tip）不得判就位"
        assert "does not contain" in reason3
        assert git(root, "rev-parse", "--verify", ref).stdout.strip() == stale_commit, \
            "陈旧引用不得被覆盖孤儿化"


# ── 场景 5：untracked 文件经引用链检出 ───────────────────────────────────────


class TestUntrackedViaRefChain:
    def test_s5_untracked_retrievable_from_ref(self, tmp_path):
        """tracked 改动 + untracked 新增：untracked 内容进快照 commit 树，
        经 refs/preservation/<run_id> 检出（非仅不可达 blob 日志留档）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("untrackme", "implementer")
        branch = wm.get_branch_name(wt)
        run_id = branch[len("fenix/"):]
        (wt / "shared.py").write_text("DIRTY\n", encoding="utf-8")
        (wt / "notes").mkdir()
        (wt / "notes" / "wip_untracked.txt").write_text("precious wip\n", encoding="utf-8")

        sha = wm._snapshot_dirty_worktree(wt, branch)

        ref = f"refs/preservation/{run_id}"
        assert sha and git(root, "rev-parse", "--verify", ref).stdout.strip() == sha
        assert git(root, "show", f"{ref}:notes/wip_untracked.txt").stdout == "precious wip\n"
        assert git(root, "show", f"{ref}:shared.py").stdout == "DIRTY\n"

    def test_s5b_untracked_only_wip_preserved_on_head_tree(self, tmp_path):
        """untracked-only WIP（stash create 空产出形态）：以 HEAD 树构
        preservation commit，untracked 照常经引用链检出。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("untrackonly", "implementer")
        branch = wm.get_branch_name(wt)
        run_id = branch[len("fenix/"):]
        # 仅 untracked：stash create 对纯 untracked 视为无改动、空产出
        (wt / "solo_wip.txt").write_text("solo\n", encoding="utf-8")

        sha = wm._snapshot_dirty_worktree(wt, branch)

        ref = f"refs/preservation/{run_id}"
        assert sha, "untracked-only WIP 也必须产出快照 commit"
        assert git(root, "rev-parse", "--verify", ref).stdout.strip() == sha
        assert git(root, "show", f"{ref}:solo_wip.txt").stdout == "solo\n"
        warns = [m for lv, _c, m in wm.logger.records if lv == "warning"]
        assert any("preserving untracked files on HEAD tree" in m for m in warns), \
            "untracked-only 回退构树路径缺 WARNING 留痕"


# ── 场景 6：clean worktree 引用指向分支 tip、分支删除后链可达 ────────────────


class TestCleanWorktreeTipAnchor:
    def test_s6_clean_ref_points_at_tip_survives_branch_delete(self, tmp_path):
        """clean worktree（交付已全部提交）：引用 = 分支 tip；分支删除后
        交付链仍经引用 for-each-ref 可达——Why 案例（已提交交付随分支删除
        丢失）的直接回归。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        wt = wm.create("cleandemo", "implementer")
        branch = wm.get_branch_name(wt)
        run_id = branch[len("fenix/"):]
        (wt / "delivery.py").write_text("CLEAN DELIVERY\n", encoding="utf-8")
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", "[fenix] cleandemo: impl")
        tip = git(wt, "rev-parse", "HEAD").stdout.strip()

        sha = wm._snapshot_dirty_worktree(wt, branch)

        ref = f"refs/preservation/{run_id}"
        assert sha == tip, "clean worktree 快照应锚定分支 tip"
        assert git(root, "rev-parse", "--verify", ref).stdout.strip() == tip
        # 分支删除后交付链仍引用可达（先移除 worktree——git 拒删被 checkout 分支）
        git(root, "worktree", "remove", "--force", str(wt))
        git(root, "branch", "-D", branch)
        names = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/").stdout
        assert branch not in names
        lst = git(root, "for-each-ref", f"--contains={tip}",
                  "--format=%(refname)", "refs/preservation/").stdout
        assert ref in lst, "分支删除后引用必须仍覆盖交付链"
        hist = git(root, "log", "--format=%s", ref).stdout
        assert "[fenix] cleandemo: impl" in hist, "已提交交付应经引用链可达"
        assert git(root, "show", f"{ref}:delivery.py").stdout == "CLEAN DELIVERY\n"

    def test_s6b_clean_branch_gc_gate_keeps_chain(self, tmp_path):
        """clean 场景经分支 GC 删除终态分支：就位门先补写引用再删分支，
        删除后交付链仍可达（spec 已终态+超期 → 引用同轮随宽限清理口径，
        fresh 写入引用存活至宽限期）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        branch = "fenix/cleangc-1013"
        merged_branch(root, branch, days_ago=30)
        tip = git(root, "rev-parse", branch).stdout.strip()

        stats = wm._gc_merged_branches()

        assert stats["deleted"] == [branch], "终态超期分支应被 GC"
        ref = "refs/preservation/cleangc-1013"
        assert ref in preservation_refs(root), "就位门应在删分支前补写引用"
        lst = git(root, "for-each-ref", f"--contains={tip}",
                  "--format=%(refname)", "refs/preservation/").stdout
        assert ref in lst, "分支删除后交付链必须仍引用可达"

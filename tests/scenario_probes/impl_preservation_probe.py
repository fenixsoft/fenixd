"""impl-worktree-preservation-refs 验证场景探针（fast-track 场景集，供 verifier 复用）。

每个 ``--case`` 在隔离临时目录构造真实 git 仓库 + 真实 WorktreeManager，
执行对应保全链路并打印单行 JSON 结果供场景 ``json_output`` 断言消费。
只触碰临时夹具仓库，不涉及真实项目仓库与真实 STATE。

case 清单（与 tasks 3.1 六场景一一对应）：
- cleanup-ref-reachable：清扫（verifier 失败 --force + branch -D）后
  refs/preservation/<run_id> 存在、--contains 分支 tip、WIP 内容可检出；
- ref-write-fallback：引用锁占位使 update-ref 真实失败 → 回退 stash sha
  + ERROR 级 git stash store 指引；
- frozen-keeps-ref：冻结在途（blocked+frozen+_frozen_hold）分支与引用
  均不删（引用已超宽限期仍保留，豁免归因冻结守卫）；
- terminal-deletes-ref：终态（done）+ 引用写入时刻超宽限期 → 同轮清理；
  宽限期内 fresh 引用保留；
- untracked-via-ref：untracked 文件经引用链检出（tracked+untracked 混合
  与 untracked-only WIP 两形态）；
- clean-tip-anchor：clean worktree 引用锚定分支 tip，分支删除后链可达。
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.worktree_manager import WorktreeManager  # noqa: E402


class FakeLogger:
    def __init__(self):
        self.records = []

    def _rec(self, level, component, msg):
        self.records.append((level, msg))

    def info(self, component, msg, context=None):
        self._rec("info", component, msg)

    def warning(self, component, msg, context=None):
        self._rec("warning", component, msg)

    def error(self, component, msg, context=None):
        self._rec("error", component, msg)


def git(root, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def build_root(tmp):
    root = tmp / "repo"
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "probe@fenix.local")
    git(root, "config", "user.name", "Fenix Probe")
    git(root, "config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    git(root, "branch", "-M", "main")
    return root


def make_wm(root):
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger(), process_scanner=lambda s: False)


def pres_refs(root):
    res = git(root, "for-each-ref", "--format=%(refname)", "refs/preservation/")
    return {ln.strip() for ln in res.stdout.splitlines() if ln.strip()}


def backdate_ref(root, run_id, days_ago):
    ref_file = root / ".git" / "refs" / "preservation" / run_id
    old = time.time() - days_ago * 86400
    os.utime(ref_file, (old, old))


def backdated(days_ago):
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S %z")


def merged_branch(root, branch, days_ago=30):
    git(root, "checkout", "-q", "main")
    git(root, "checkout", "-q", "-b", branch)
    env = dict(os.environ,
               GIT_AUTHOR_DATE=backdated(days_ago),
               GIT_COMMITTER_DATE=backdated(days_ago))
    (root / "feat.py").write_text(f"{branch}\n", encoding="utf-8")
    git(root, "add", "-A")
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", f"[fenix] {branch}"],
                   capture_output=True, env=env, check=True)
    git(root, "checkout", "-q", "main")
    git(root, "merge", "-q", "--ff-only", branch)


def make_state(root, specs):
    from core.state_machine import StateMachine
    state_path = root / ".fenix" / "STATE.md"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    sm = StateMachine(state_path, FakeLogger())
    for name, entry in specs.items():
        sm.add_spec(name, entry)


# ── case 1：清扫后 refs/preservation/<run_id> 存在且交付链 --contains 可达 ────


def case_cleanup_ref_reachable(tmp):
    root = build_root(tmp)
    wm = make_wm(root)
    wt = wm.create("presdemo", "verifier")
    branch = wm.get_branch_name(wt)
    run_id = branch[len("fenix/"):]
    (wt / "delivery.py").write_text("DELIVERY v1\n", encoding="utf-8")
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", "[fenix] presdemo: impl")
    pre_tip = git(wt, "rev-parse", "HEAD").stdout.strip()
    (wt / "shared.py").write_text("DIRTY\n", encoding="utf-8")
    (wt / "wip_untracked.txt").write_text("precious wip\n", encoding="utf-8")

    wm.cleanup(wt, success=False)

    ref = f"refs/preservation/{run_id}"
    ref_sha = git(root, "rev-parse", "--verify", ref).stdout.strip()
    contains = git(root, "for-each-ref", f"--contains={pre_tip}",
                   "--format=%(refname)", "refs/preservation/").stdout
    heads = git(root, "for-each-ref", "--format=%(refname:short)",
                "refs/heads/").stdout
    checks = {
        "worktree_removed": not wt.exists(),
        "branch_deleted": branch not in heads,
        "ref_exists": ref in pres_refs(root),
        "ref_is_commit": git(root, "cat-file", "-t", ref_sha).stdout.strip() == "commit",
        "ref_contains_pre_tip": ref in contains,
        "committed_delivery_reachable": "[fenix] presdemo: impl" in git(
            root, "log", "--format=%s", ref_sha).stdout,
        "tracked_wip_retrievable": git(root, "show", f"{ref}:shared.py").stdout == "DIRTY\n",
        "untracked_wip_retrievable": git(
            root, "show", f"{ref}:wip_untracked.txt").stdout == "precious wip\n",
    }
    return checks


# ── case 2：update-ref 失败回退现状行为并升 ERROR ────────────────────────────


def case_ref_write_fallback(tmp):
    root = build_root(tmp)
    wm = make_wm(root)
    wt = wm.create("faildemo", "implementer")
    branch = wm.get_branch_name(wt)
    run_id = branch[len("fenix/"):]
    (wt / "shared.py").write_text("DIRTY\n", encoding="utf-8")
    (wt / "wip_new.txt").write_text("wip\n", encoding="utf-8")
    # 陈旧引用锁：update-ref cannot lock ref（真实失败路径）
    lock = root / ".git" / "refs" / "preservation" / f"{run_id}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("", encoding="utf-8")

    sha = wm._snapshot_dirty_worktree(wt, branch)
    errs = [m for lv, m in wm.logger.records if lv == "error"]

    checks = {
        "fallback_sha_returned": bool(sha) and git(
            root, "rev-parse", "--verify", sha, check=False).returncode == 0,
        "no_ref_left": f"refs/preservation/{run_id}" not in pres_refs(root),
        "error_logged": any(
            "Pre-rmtree preservation ref write FAILED" in m and "git stash store" in m
            for m in errs),
    }
    lock.unlink()
    return checks


# ── case 3：冻结在途不删引用 ─────────────────────────────────────────────────


def case_frozen_keeps_ref(tmp):
    root = build_root(tmp)
    wm = make_wm(root)
    branch = "fenix/frozenkeeper-1009"
    merged_branch(root, branch)
    tip = git(root, "rev-parse", branch).stdout.strip()
    ref = "refs/preservation/frozenkeeper-1009"
    git(root, "update-ref", ref, tip)
    backdate_ref(root, "frozenkeeper-1009", days_ago=30)
    make_state(root, {"frozenkeeper": {
        "status": "blocked", "frozen": True, "_frozen_hold": True}})

    stats = wm._gc_merged_branches()
    heads = git(root, "for-each-ref", "--format=%(refname:short)",
                "refs/heads/").stdout
    checks = {
        "branch_kept": branch in heads,
        "ref_kept": ref in pres_refs(root),
        "zero_deleted": stats.get("deleted") == [],
        "zero_ref_deleted": stats.get("preservation_deleted") == [],
        "frozen_exempt_counted": stats.get("preservation_frozen") == 1,
    }
    return checks


# ── case 4：终态消费后清理引用 ───────────────────────────────────────────────


def case_terminal_deletes_ref(tmp):
    root = build_root(tmp)
    wm = make_wm(root)
    branch = "fenix/donepres-1010"
    merged_branch(root, branch)
    tip = git(root, "rev-parse", branch).stdout.strip()
    ref = "refs/preservation/donepres-1010"
    git(root, "update-ref", ref, tip)
    backdate_ref(root, "donepres-1010", days_ago=30)
    make_state(root, {"donepres": {"status": "done"}})

    stats = wm._gc_merged_branches()

    # 对照组：终态但引用写入时刻新鲜（宽限期内）→ 保留
    branch2 = "fenix/donefresh-1011"
    merged_branch(root, branch2)
    ref2 = "refs/preservation/donefresh-1011"
    git(root, "update-ref", ref2, git(root, "rev-parse", branch2).stdout.strip())
    stats2 = wm._gc_merged_branches()

    checks = {
        "stale_branch_deleted": stats.get("deleted") == [branch],
        "stale_ref_deleted": stats.get("preservation_deleted") == [ref],
        "stale_ref_gone": ref not in pres_refs(root),
        "fresh_ref_kept_within_grace": ref2 in pres_refs(root),
        "fresh_ref_not_deleted": stats2.get("preservation_deleted") == [],
    }
    return checks


# ── case 5：untracked 文件经引用链检出 ───────────────────────────────────────


def case_untracked_via_ref(tmp):
    root = build_root(tmp)
    wm = make_wm(root)
    # 形态 A：tracked 改动 + untracked 新增（含子目录）
    wt = wm.create("untrackme", "implementer")
    branch = wm.get_branch_name(wt)
    run_id = branch[len("fenix/"):]
    (wt / "shared.py").write_text("DIRTY\n", encoding="utf-8")
    (wt / "notes").mkdir()
    (wt / "notes" / "wip_untracked.txt").write_text("precious wip\n", encoding="utf-8")
    sha = wm._snapshot_dirty_worktree(wt, branch)
    ref = f"refs/preservation/{run_id}"
    a_ok = (
        bool(sha)
        and git(root, "rev-parse", "--verify", ref).stdout.strip() == sha
        and git(root, "show", f"{ref}:notes/wip_untracked.txt").stdout == "precious wip\n"
        and git(root, "show", f"{ref}:shared.py").stdout == "DIRTY\n"
    )
    # 形态 B：untracked-only（stash create 空产出）→ HEAD 树构 preservation commit
    wt2 = wm.create("untrackonly", "implementer")
    branch2 = wm.get_branch_name(wt2)
    run_id2 = branch2[len("fenix/"):]
    (wt2 / "solo_wip.txt").write_text("solo\n", encoding="utf-8")
    sha2 = wm._snapshot_dirty_worktree(wt2, branch2)
    ref2 = f"refs/preservation/{run_id2}"
    b_ok = (
        bool(sha2)
        and git(root, "rev-parse", "--verify", ref2).stdout.strip() == sha2
        and git(root, "show", f"{ref2}:solo_wip.txt").stdout == "solo\n"
    )
    warns = [m for lv, m in wm.logger.records if lv == "warning"]
    checks = {
        "mixed_untracked_via_ref": a_ok,
        "untracked_only_via_ref": b_ok,
        "head_tree_fallback_logged": any(
            "preserving untracked files on HEAD tree" in m for m in warns),
    }
    return checks


# ── case 6：clean worktree 引用指向分支 tip、分支删除后链可达 ─────────────────


def case_clean_tip_anchor(tmp):
    root = build_root(tmp)
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
    anchored = sha == tip and git(
        root, "rev-parse", "--verify", ref).stdout.strip() == tip
    # 分支删除后交付链仍引用可达
    git(root, "worktree", "remove", "--force", str(wt))
    git(root, "branch", "-D", branch)
    contains = git(root, "for-each-ref", f"--contains={tip}",
                   "--format=%(refname)", "refs/preservation/").stdout
    checks = {
        "ref_anchored_to_tip": anchored,
        "branch_deleted": branch not in git(
            root, "for-each-ref", "--format=%(refname:short)",
            "refs/heads/").stdout,
        "chain_reachable_after_delete": ref in contains,
        "delivery_retrievable": git(
            root, "show", f"{ref}:delivery.py").stdout == "CLEAN DELIVERY\n",
        "commit_log_reachable": "[fenix] cleandemo: impl" in git(
            root, "log", "--format=%s", ref).stdout,
    }
    return checks


CASES = {
    "cleanup-ref-reachable": case_cleanup_ref_reachable,
    "ref-write-fallback": case_ref_write_fallback,
    "frozen-keeps-ref": case_frozen_keeps_ref,
    "terminal-deletes-ref": case_terminal_deletes_ref,
    "untracked-via-ref": case_untracked_via_ref,
    "clean-tip-anchor": case_clean_tip_anchor,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=sorted(CASES))
    args = parser.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="impl-pres-probe-"))
    try:
        checks = CASES[args.case](tmp)
        failed = [k for k, v in checks.items() if not v]
        out = {
            "case": args.case,
            "pass": not failed,
            "checks": checks,
            "failed": failed,
        }
    except Exception as e:  # noqa: BLE001 — 探针异常统一折算为 fail 输出
        out = {"case": args.case, "pass": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        subprocess.run(["rm", "-rf", str(tmp)], capture_output=True)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0 if out.get("pass") else 1)


if __name__ == "__main__":
    main()

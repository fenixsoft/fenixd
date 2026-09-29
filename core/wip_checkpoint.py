"""
wip_checkpoint.py — WIP checkpoint 提交与 merge-back 塌缩（add-impl-wip-checkpoint）。

框架控制的 WIP 提交只出现在三处可证明 agent 不再写盘的生命周期锚点：
  - 锚点 A（drain-preserve）：排水超时收口路径——所有在飞 agent 进程终止
    完成后（wait_for_running_agents 返回）、cleanup_orphans 之前，对保全集
    worktree 逐个提交（D2）。
  - 锚点 B（transient-backoff）：runner attempt 循环判定瞬断、写入
    transient_retry 记录后、进入 time.sleep(backoff) 前，对当前 attempt 的
    worktree 提交（D3）。
  - 锚点 C（turn-limit）：轮询环判定 run 触达 max_turns 轮次上限并对子进程
    执行终止（kill 序列）后、异常收口（append_run_error + raise）前，对当前
    attempt 的 worktree 提交——保全零提交型强杀现场（add-turn-limit-anchor-c
    D1：builtin a1 84min 未提交工作滞留 worktree 的事故补位）。

消息契约（D5）：``fenix(wip): checkpoint <anchor> <spec>``，机器可识别前缀
供 merge-back 前塌缩（D4）扫描与人工审计。提交尊重 worktree 的 gitignore
（git add -A 天然排除 ignored）。

失败降级（D6）：所有 git 操作 15s 超时，失败仅 WARNING 留痕并继续既有收口/
重试流程——WIP 提交是尽力而为的保全增强，任何失败不改变现行行为。
"""

import subprocess
from typing import Any

WIP_COMMIT_PREFIX = "fenix(wip):"
WIP_TIMEOUT_SECONDS = 15

ANCHOR_DRAIN_PRESERVE = "drain-preserve"
ANCHOR_TRANSIENT_BACKOFF = "transient-backoff"
ANCHOR_TURN_LIMIT = "turn-limit"
ANCHOR_EXTENSION_TAIL = "extension-tail"
ANCHOR_FREEZE_HOLD = "freeze-hold"


# ── 锚点提交（锚点 A / B 共用，D5/D6）───────────────────────────────────────


def commit_wip_checkpoint(
    wt_path: Any,
    spec: str,
    anchor: str,
    logger: Any,
    *,
    timeout: int = WIP_TIMEOUT_SECONDS,
) -> bool:
    """对 worktree 执行一次 WIP checkpoint 提交（尽力而为、不阻塞）。

    - ``git status --porcelain`` 为空 → 跳过（不产生空提交，幂等）
    - ``git add -A``（尊重 worktree gitignore）+ ``git commit``
    - 每个 git 操作限时 ``timeout`` 秒；失败/超时 → WARNING 留痕、返回 False
    - 子树已在 git 内不可见/目录丢失等，一律按失败降级

    Returns: True 表示产生了一次提交；False 表示跳过（无变更）或失败。
    """
    path = str(wt_path)
    try:
        st = subprocess.run(
            ["git", "-C", path, "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if st.returncode != 0:
            logger.warning(
                "wip_checkpoint",
                f"WIP checkpoint (anchor '{anchor}', spec '{spec}') "
                f"git status failed in '{path}': "
                f"{st.stderr.strip() or st.stdout.strip()} — skip (non-blocking)",
            )
            return False
        if not st.stdout.strip():
            return False  # 空变更：幂等跳过
        add = subprocess.run(
            ["git", "-C", path, "add", "-A"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if add.returncode != 0:
            logger.warning(
                "wip_checkpoint",
                f"WIP checkpoint (anchor '{anchor}', spec '{spec}') "
                f"git add failed in '{path}': "
                f"{add.stderr.strip() or add.stdout.strip()} — skip (non-blocking)",
            )
            return False
        message = f"{WIP_COMMIT_PREFIX} checkpoint {anchor} {spec}"
        cm = subprocess.run(
            ["git", "-C", path, "commit", "-m", message],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if cm.returncode != 0:
            logger.warning(
                "wip_checkpoint",
                f"WIP checkpoint (anchor '{anchor}', spec '{spec}') "
                f"git commit failed in '{path}': "
                f"{cm.stderr.strip() or cm.stdout.strip()} — skip (non-blocking)",
            )
            return False
        # 并发 WIP 竞态：同一 worktree 内 add 后 commit 前若又被改动（理论
        # 上极小，锚点时刻 worktree 静默），git commit 仍可能成功收编同批
        # 变更；本 helper 只保证不丢工作、不误报。
        logger.info(
            "wip_checkpoint",
            f"WIP checkpoint committed (anchor '{anchor}', spec '{spec}') "
            f"in '{path}': {message}",
        )
        return True
    except subprocess.TimeoutExpired:
        logger.warning(
            "wip_checkpoint",
            f"WIP checkpoint (anchor '{anchor}', spec '{spec}') timed out "
            f"after {timeout}s in '{path}' — skip (non-blocking)",
        )
        return False
    except (OSError, ValueError) as e:
        # UnicodeDecodeError 属 ValueError 族：解码失败同样按失败降级，不外溢。
        logger.warning(
            "wip_checkpoint",
            f"WIP checkpoint (anchor '{anchor}', spec '{spec}') failed in "
            f"'{path}': {e} — skip (non-blocking)",
        )
        return False


# ── merge-back 前塌缩（D4）───────────────────────────────────────────────────


def _collapse_message(project_root, commits, logger, timeout=WIP_TIMEOUT_SECONDS):
    """塌缩单提交的提交消息：取自塌缩前最终提交。

    - 分支上有非 WIP 最终提交 → 使用其完整消息（Spec 3.2「消息取自最终提交」）；
      ``commits`` 以 tip 在前（git log 新→旧），取列表中第一个（即最新）非 WIP
      提交，覆盖最终提交被 WIP 夹在中间的交错形态（[wip, final, wip]）
    - 分支最新提交也是 WIP（仅 WIP 无最终提交）→ 以前缀改写生成非 WIP 消息
      （``fenix(wip):`` → ``[fenix]``），保证主树合并历史无 wip 前缀残留

    Returns: (message, ok)。ok=False 表示消息获取失败（调用方按失败降级）。
    """
    final_hash, final_subject = next(
        ((h, s) for h, s in commits if not s.startswith(WIP_COMMIT_PREFIX)),
        commits[0],
    )
    body = subprocess.run(
        ["git", "-C", str(project_root), "log", "-1", "--format=%B", final_hash],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if body.returncode == 0 and body.stdout.strip():
        if final_subject.startswith(WIP_COMMIT_PREFIX):
            # 仅 WIP 无最终提交：以最新 WIP 的完整消息改写前缀生成塌缩消息。
            return body.stdout.replace(WIP_COMMIT_PREFIX, "[fenix]", 1), True
        return body.stdout, True
    # git log 失败/正文为空：消息获取失败，返回占位 subject 并置 ok=False，
    # 由调用方按失败降级（放弃本次塌缩）。
    if final_subject.startswith(WIP_COMMIT_PREFIX):
        return final_subject.replace(WIP_COMMIT_PREFIX, "[fenix]", 1), False
    return final_subject, False


def collapse_wip_commits(
    project_root: Any,
    branch: str,
    logger: Any,
    *,
    timeout: int = WIP_TIMEOUT_SECONDS,
) -> bool:
    """把分支上的全部 ``fenix(wip):`` 前缀提交塌缩为单提交（merge-back 前）。

    ``git merge-base HEAD branch`` 为基点：先读分支 tip commit sha 作 CAS
    旧值，再以该 tip 解析 tree（与旧值同一时点）经 ``git commit-tree`` 重建
    一个父为基点的单提交，``git update-ref`` 带 CAS 移动分支引用——窗口期
    分支被并发写入新提交时 CAS 失败、放弃塌缩，不会把引用指回旧 tip tree
    而丢掉新提交。
    soft-reset 语义等效（工作区/索引不动，文件内容逐字节不变），
    且不依赖分支所在 worktree 是否存在（纯 ref 操作，无 checkout）。

    幂等：分支上无 ``fenix(wip):`` 前缀提交时零动作（常规成功路径逐字节
    现行行为）。重入（merge-back 失败后重试）时 WIP 已塌缩，零动作无害。

    Returns: True 表示发生了塌缩；False 表示零动作或失败（调用方按失败
    降级，merge-back 以未塌缩分支继续，行为与现行一致）。
    """
    try:
        mb = subprocess.run(
            ["git", "-C", str(project_root), "merge-base", "HEAD", branch],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if mb.returncode != 0 or not mb.stdout.strip():
            return False
        mb_sha = mb.stdout.strip()
        log = subprocess.run(
            ["git", "-C", str(project_root), "log", "--format=%H\t%s", f"{mb_sha}..{branch}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if log.returncode != 0 or not log.stdout.strip():
            return False
        commits = []
        for line in log.stdout.splitlines():
            if "\t" in line:
                h, s = line.split("\t", 1)
                commits.append((h, s))
        if not commits:
            return False
        if not any(s.startswith(WIP_COMMIT_PREFIX) for _h, s in commits):
            return False  # 无 WIP：零动作

        # CAS 旧值：先读分支 tip commit sha（非 tree sha），供 update-ref
        # 比较并交换——塌缩窗口内分支被写入新提交时 CAS 失败、放弃塌缩。
        tip = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", f"refs/heads/{branch}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if tip.returncode != 0 or not tip.stdout.strip():
            logger.warning(
                "wip_checkpoint",
                f"WIP collapse for branch '{branch}' failed to resolve tip — "
                f"merge-back continues on uncollapsed branch (non-blocking)",
            )
            return False
        # 树以该 tip 解析而非现读 branch^{tree}：树与 CAS 旧值同一时点，
        # 否则两读之间新落的提交会被「旧树+新 tip 旧值」的 CAS 放行整笔丢弃。
        tree = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", f"{tip.stdout.strip()}^{{tree}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if tree.returncode != 0 or not tree.stdout.strip():
            logger.warning(
                "wip_checkpoint",
                f"WIP collapse for branch '{branch}' failed to resolve tree — "
                f"merge-back continues on uncollapsed branch (non-blocking)",
            )
            return False
        message, ok = _collapse_message(project_root, commits, logger, timeout=timeout)
        if not ok:
            return False
        ct = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "commit-tree",
                tree.stdout.strip(),
                "-p",
                mb_sha,
                "-m",
                message,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if ct.returncode != 0 or not ct.stdout.strip():
            logger.warning(
                "wip_checkpoint",
                f"WIP collapse for branch '{branch}' commit-tree failed: "
                f"{ct.stderr.strip() or ct.stdout.strip()} — merge-back "
                f"continues on uncollapsed branch (non-blocking)",
            )
            return False
        upd = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "update-ref",
                f"refs/heads/{branch}",
                ct.stdout.strip(),
                tip.stdout.strip(),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if upd.returncode != 0:
            logger.warning(
                "wip_checkpoint",
                f"WIP collapse for branch '{branch}' update-ref failed "
                f"(tip moved concurrently or ref error): "
                f"{upd.stderr.strip() or upd.stdout.strip()} — merge-back "
                f"continues on uncollapsed branch (non-blocking)",
            )
            return False
        logger.info(
            "wip_checkpoint",
            f"WIP collapse for branch '{branch}': "
            f"{len([c for c in commits if c[1].startswith(WIP_COMMIT_PREFIX)])} "
            f"WIP commit(s) collapsed into 1 (message from final commit)",
        )
        return True
    except subprocess.TimeoutExpired:
        logger.warning(
            "wip_checkpoint",
            f"WIP collapse for branch '{branch}' timed out after {timeout}s — "
            f"merge-back continues on uncollapsed branch (non-blocking)",
        )
        return False
    except (OSError, ValueError) as e:
        # UnicodeDecodeError 属 ValueError 族：解码失败同样按失败降级，不外溢。
        logger.warning(
            "wip_checkpoint",
            f"WIP collapse for branch '{branch}' failed: {e} — merge-back "
            f"continues on uncollapsed branch (non-blocking)",
        )
        return False

"""
wip_checkpoint.py — WIP checkpoint 提交与 merge-back 塌缩（add-impl-wip-checkpoint）。

框架控制的 WIP 提交只出现在以下可证明 agent 不再写盘的生命周期锚点：
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
  - 锚点 E（extension-tail）：fast-track run 剩余时间进入末位窗口
    （remaining < EXTENSION_TAIL_WINDOW_SECONDS）时、超时收口尚未到点前，
    对当前 attempt 的 worktree 提交，run 继续轮询——超时到点后走既有
    收口，已完成轮次工作不随超时无保全作废（add-fast-track-scale-
    precheck D3）。
  - 锚点 F（freeze-hold）：轮询环检测到 spec 级冻结旗标命中、对仍存活
    的子进程执行 terminate/grace/kill 终止序列前，对当前 attempt 的
    worktree 提交——冻结终止即停，不再有下一 attempt 的退避窗口保全
    机会（add-freeze-stop-inflight-agents D1）。
  - 锚点 D（cancel）：run 取消路径——取消旗标在轮询环内确认命中、
    terminate/grace/kill 序列完成后、收口异常构造前，对当前 attempt 的
    worktree 提交（RunCancelledError 收口分支再兜底一次；add-run-cancel-
    wip-checkpoint：用户取消但现场已保全，审计可区分取消与损失）。

消息契约（D5）：``fenix(wip): checkpoint <anchor> <spec>``，机器可识别前缀
供 merge-back 前塌缩（D4）扫描与人工审计。塌缩（D4）把 merge-base 到分支
tip 的整段区间折叠为单提交：区间内全部提交（含非 WIP 的常规提交）一并
进入该单提交、从分支可达历史上消失，消息取区间内最终非 WIP 提交（仅
WIP 时改写前缀）。提交尊重 worktree 的 gitignore
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
ANCHOR_CANCEL = "cancel"
ANCHOR_STALL_BUDGET = "stall-budget"


def _git(args: list, cwd: str, timeout: int) -> subprocess.CompletedProcess:
    """模块内 git 子进程调用统一入口：集中承载 capture_output/text/
    encoding/errors/timeout 五件套（D6 编码容错与超时口径的唯一出处），
    调用点只保留 git 子命令与语义判断。返回 CompletedProcess，由调用点
    按 returncode/stdout/stderr 判定；TimeoutExpired/OSError/ValueError
    仍由调用方既有 try/except 兜底降级。"""
    return subprocess.run(
        ["git", "-C", cwd, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


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
    - index 回滚（git reset）仅在 ``git add`` 已实际发出后的失败/超时路径
      执行；status 阶段失败/超时不动 index，不误撤销 agent 既有 staged 现场
    - 子树已在 git 内不可见/目录丢失等，一律按失败降级

    Returns: True 表示产生了一次提交；False 表示跳过（无变更）或失败。
    """
    path = str(wt_path)
    added = False  # add 已实际发出后置 True：index 回滚仅覆盖被本函数改写过的 index
    try:
        st = _git(["status", "--porcelain"], path, timeout)
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
        added = True
        add = _git(["add", "-A"], path, timeout)
        if add.returncode != 0:
            logger.warning(
                "wip_checkpoint",
                f"WIP checkpoint (anchor '{anchor}', spec '{spec}') "
                f"git add failed in '{path}': "
                f"{add.stderr.strip() or add.stdout.strip()} — skip (non-blocking)",
            )
            # git add -A 非原子：部分文件已暂存后才遇到不可读路径等错误即
            # exit 非零，index 已被本函数部分改写——与 commit 失败分支同理，
            # 残留 partial staged 现场被 keep_for_reuse 后继继承后使以 HEAD
            # 为基准的留证链路判读失真。补一次尽力而为的 mixed reset 回滚；
            # reset 自身失败仅追加留痕，不改变本函数返回值与既有降级语义。
            reset = _git(["reset", "-q"], path, timeout)
            if reset.returncode != 0:
                logger.warning(
                    "wip_checkpoint",
                    f"WIP checkpoint (anchor '{anchor}', spec '{spec}') "
                    f"index rollback (git reset) after failed add failed "
                    f"in '{path}': "
                    f"{reset.stderr.strip() or reset.stdout.strip()} "
                    f"— ignore (non-blocking)",
                )
            return False
        message = f"{WIP_COMMIT_PREFIX} checkpoint {anchor} {spec}"
        cm = _git(["commit", "-m", message], path, timeout)
        if cm.returncode != 0:
            logger.warning(
                "wip_checkpoint",
                f"WIP checkpoint (anchor '{anchor}', spec '{spec}') "
                f"git commit failed in '{path}': "
                f"{cm.stderr.strip() or cm.stdout.strip()} — skip (non-blocking)",
            )
            # add -A 已整树暂存而 commit 失败：mixed reset 把 index 恢复到
            # HEAD（不动工作区），避免 worktree 以「全量 staged、与 HEAD
            # 分叉」的现场被后继 run 继承（keep_for_reuse 认领同一目录），
            # 使 _snapshot_dirty_worktree/collapse 等以 HEAD 为基准的留证
            # 链路判读失真。尽力而为的失败不留副作用：reset 自身失败仅
            # 追加留痕，不改变本函数返回值与既有降级语义。
            reset = _git(["reset", "-q"], path, timeout)
            if reset.returncode != 0:
                logger.warning(
                    "wip_checkpoint",
                    f"WIP checkpoint (anchor '{anchor}', spec '{spec}') "
                    f"index rollback (git reset) after failed commit failed "
                    f"in '{path}': "
                    f"{reset.stderr.strip() or reset.stdout.strip()} "
                    f"— ignore (non-blocking)",
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
            f"after {timeout}s in '{path}' — skip (non-blocking); the "
            f"force-killed git subprocess may leave a stale lock (index.lock "
            f"under the worktree gitdir) — if later git ops keep failing with "
            f"lock conflicts, inspect and remove it manually",
        )
        # 超时可能落在 status / add / commit 任一阶段：仅当 add 已实际发出
        # （added=True）后 index 才被本函数改写过（add 已完成、commit 卡住/
        # 被杀的窗口内为全量 staged 态，与上方 commit 失败分支要防的现场
        # 一致——被 keep_for_reuse 后继继承后使以 HEAD 为基准的留证链路
        # 判读失真），此刻补一次尽力而为的 mixed reset 回滚；status 阶段
        # 超时则 index 仍是 agent 既有现场（staged 删除、intent-to-add 等
        # 摘索引形态），reset 会误撤销之——直接留痕返回。本分支已在原 try
        # 的 except 内，reset 自身的二次超时/OS/解码异常须就地兜住，失败
        # 仅追加留痕，不改返回值。
        if not added:
            return False
        try:
            reset = _git(["reset", "-q"], path, timeout)
            if reset.returncode != 0:
                logger.warning(
                    "wip_checkpoint",
                    f"WIP checkpoint (anchor '{anchor}', spec '{spec}') "
                    f"index rollback (git reset) after timed-out checkpoint "
                    f"failed in '{path}': "
                    f"{reset.stderr.strip() or reset.stdout.strip()} "
                    f"— ignore (non-blocking)",
                )
        except (subprocess.TimeoutExpired, OSError, ValueError) as reset_err:
            logger.warning(
                "wip_checkpoint",
                f"WIP checkpoint (anchor '{anchor}', spec '{spec}') index "
                f"rollback (git reset) after timed-out checkpoint failed "
                f"in '{path}': {reset_err} — ignore (non-blocking)",
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


def _collapse_message(project_root, commits, timeout=WIP_TIMEOUT_SECONDS):
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
    body = _git(["log", "-1", "--format=%B", final_hash], str(project_root), timeout)
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
    """把 merge-base 到分支 tip 的整段区间塌缩为单提交（merge-back 前）。

    塌缩对象不止 ``fenix(wip):`` 前缀提交：区间内全部提交（含非 WIP 的
    常规提交）一并折叠进这单提交、从分支可达历史上消失；仅当区间内存在
    WIP 前缀提交才触发，消息取最终非 WIP 提交（仅 WIP 时改写前缀）。

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
        mb = _git(["merge-base", "HEAD", branch], str(project_root), timeout)
        if mb.returncode != 0 or not mb.stdout.strip():
            return False
        mb_sha = mb.stdout.strip()
        # CAS 旧值：先读分支 tip commit sha（非 tree sha），供 update-ref
        # 比较并交换——塌缩窗口内分支被写入新提交时 CAS 失败、放弃塌缩。
        # tip 必须先于区间 log 读取，log 以该 tip sha（而非 branch 符号名）
        # 取数：WIP 判定、消息选择、tree、CAS 旧值全部锚定同一 tip 时点，
        # 闭合两读窗口——否则 log 与 tip 之间新落的提交会被 CAS 放行折叠
        # 丢失其提交消息，或使 WIP 判定按旧区间漏判（仅窗口内有 WIP 时
        # 零动作放行，wip 前缀提交进入主树合并历史）。
        tip = _git(["rev-parse", f"refs/heads/{branch}"], str(project_root), timeout)
        if tip.returncode != 0 or not tip.stdout.strip():
            logger.warning(
                "wip_checkpoint",
                f"WIP collapse for branch '{branch}' failed to resolve tip — "
                f"merge-back continues on uncollapsed branch (non-blocking)",
            )
            return False
        log = _git(
            ["log", "--format=%H\t%s", f"{mb_sha}..{tip.stdout.strip()}"],
            str(project_root),
            timeout,
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
        # 树以该 tip 解析而非现读 branch^{tree}：树与 CAS 旧值同一时点，
        # 否则两读之间新落的提交会被「旧树+新 tip 旧值」的 CAS 放行整笔丢弃。
        tree = _git(
            ["rev-parse", f"{tip.stdout.strip()}^{{tree}}"],
            str(project_root),
            timeout,
        )
        if tree.returncode != 0 or not tree.stdout.strip():
            logger.warning(
                "wip_checkpoint",
                f"WIP collapse for branch '{branch}' failed to resolve tree — "
                f"merge-back continues on uncollapsed branch (non-blocking)",
            )
            return False
        message, ok = _collapse_message(project_root, commits, timeout=timeout)
        if not ok:
            logger.warning(
                "wip_checkpoint",
                f"WIP collapse for branch '{branch}' failed to read final "
                f"commit message — merge-back continues on uncollapsed "
                f"branch (non-blocking)",
            )
            return False
        ct = _git(
            ["commit-tree", tree.stdout.strip(), "-p", mb_sha, "-m", message],
            str(project_root),
            timeout,
        )
        if ct.returncode != 0 or not ct.stdout.strip():
            logger.warning(
                "wip_checkpoint",
                f"WIP collapse for branch '{branch}' commit-tree failed: "
                f"{ct.stderr.strip() or ct.stdout.strip()} — merge-back "
                f"continues on uncollapsed branch (non-blocking)",
            )
            return False
        upd = _git(
            [
                "update-ref",
                f"refs/heads/{branch}",
                ct.stdout.strip(),
                tip.stdout.strip(),
            ],
            str(project_root),
            timeout,
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
            f"merge-back continues on uncollapsed branch (non-blocking); the "
            f"force-killed git subprocess may leave a stale lock "
            f"(<gitdir>/refs/heads/{branch}.lock or packed-refs.lock) — if "
            f"later update-ref/merge-back ops keep failing with lock "
            f"conflicts, inspect and remove it manually",
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

"""归档自动提交（archive-auto-commit 即时化）。

归档移动（``spec/changes/<name>/`` → ``spec/archive/<dir>/``）成功后立即在
项目仓库产生一次 pathspec 限定的提交，不再等 push 流程尾部收口：

- 仅提交归档两条路径（changes 删除侧 + archive 新增侧）：``git add --`` +
  ``git commit -m ... --`` 同一 pathspec（--only 语义），不吞索引中无关
  staged 内容、不扫进 spec/ 下其它正在修改的文件；
- fail-open：非 git 仓库 / git 失败一律以 ``warning`` 返回，不抛异常、
  不回滚已成功的目录移动，归档本体不受影响；
- 只 commit 不 push：push 仍由人工门禁（fenix-approve）与 push 流程负责；
  pm_engine push 尾部的归档收口保留为兜底（有残留才动作）。
"""

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger("fenixd.archive_commit")

_PROBE_TIMEOUT = 30
_ADD_TIMEOUT = 60
_COMMIT_TIMEOUT = 120
# pathspec 安全白名单：spec_name / 归档目录名允许的合法字符集
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def commit_archive_move(project_root, spec_name: str, archive_dir, distill=None) -> dict:
    """提交一次归档移动（只 commit，不 push），并单点挂载蒸馏派发。

    Args:
        project_root: 项目根目录
        spec_name: SPEC 名（用于提交信息）
        archive_dir: 移动后的归档目录路径（Path/str）
        distill: 蒸馏派发替身（task 2.3 测试隔离）。None = 延迟导入
            ``core.knowledge.dispatch_distill`` 走真实派发（内部另有
            knowledge.enabled 门控与 pytest 环境守卫——既有单测直接调用
            本函数不会触发真实蒸馏）。

    Returns:
        {"committed": bool, "commit": str|null, "warning": str|null,
         "distill": {"dispatched": bool, "reason": str|null}|null}
        - committed=True：提交成功，commit 为本次提交的全量 hash
          （哈希读取失败时为 null，提交本身已落库）；
        - committed=False：warning 说明原因（非 git 仓库 / git 失败 / 无可提交内容）；
        - distill 为 None 仅当 git 探测失败提前返回（派发只在 git 仓库内进行）。
    """
    proot = Path(project_root)
    result = {"committed": False, "commit": None, "warning": None}

    def _fail(msg: str) -> dict:
        result["warning"] = msg
        return result

    # 非 git 仓库 / git 不可用 → fail-open
    try:
        probe = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
        if probe.returncode != 0 or probe.stdout.strip() != "true":
            return _fail(
                "非 git 仓库，跳过归档提交: "
                + (probe.stderr.strip() or probe.stdout.strip() or f"exit {probe.returncode}")
            )
    except (OSError, subprocess.TimeoutExpired) as e:
        return _fail(f"git 探测失败，跳过归档提交: {e}")

    # ── 知识蒸馏派发（add-knowledge-atlas task 2.3，双路径单点漏斗）──────
    # 归档移动成功即触发（不依赖本次提交成败）。fail-open：派发异常只记日志
    # 与重试台账，不影响归档提交主流程；内部 knowledge.enabled 门控与
    # pytest 守卫由 dispatch_distill 承担。延迟导入避免模块级依赖环。
    result["distill"] = None
    try:
        if distill is None:
            from core.knowledge import dispatch_distill

            distill = dispatch_distill
        result["distill"] = distill(proot, Path(archive_dir).name)
    except Exception as e:  # noqa: BLE001 — 派发任何异常不阻塞归档
        logger.warning(
            "知识蒸馏派发异常（archive=%s）: %s: %s",
            Path(archive_dir).name,
            type(e).__name__,
            e,
        )
        result["distill"] = {"dispatched": False, "reason": f"error: {e}"}

    # pathspec 安全：spec_name / 归档目录名直接拼入 git pathspec，glob（* ? []）
    # 会被按模式匹配解释而可能误匹配计划外路径；白名单不通过时 fail-open 跳过提交。
    if not (
        _SAFE_PATH_RE.match(spec_name)
        and _SAFE_PATH_RE.match(Path(archive_dir).name)
    ):
        return _fail(
            "spec_name 或归档目录名含 pathspec 危险字符，跳过归档提交: "
            f"{spec_name!r} / {Path(archive_dir).name!r}"
        )

    # pathspec 组装：changes 侧仅在存在目录或存在跟踪文件时参与——从未入库的
    # spec 归档后该路径 matches nothing，会让整条 git add fatal 退出。
    changes_side = f"spec/changes/{spec_name}"
    archive_side = f"spec/archive/{Path(archive_dir).name}"
    paths = []
    if (proot / archive_side).exists():
        paths.append(archive_side)
    if (proot / changes_side).exists() or _has_tracked_files(proot, changes_side):
        paths.append(changes_side)
    if not paths:
        return _fail("归档路径均无可提交内容，跳过归档提交")

    commit_msg = f"[fenix] archive: {spec_name} 归档入库"
    try:
        add = subprocess.run(
            ["git", "add", "--"] + paths,
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_ADD_TIMEOUT,
        )
        if add.returncode != 0:
            return _fail(f"git add 失败: {add.stderr.strip() or f'exit {add.returncode}'}")
        commit = subprocess.run(
            ["git", "commit", "-m", commit_msg, "--"] + paths,
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_COMMIT_TIMEOUT,
        )
        if commit.returncode != 0:
            _unstage(proot, paths)
            return _fail(f"git commit 失败: {commit.stderr.strip() or f'exit {commit.returncode}'}")
        # 提交已落库，先行置位：后续读哈希若因超时/OSError 失败，不能回退成
        # committed=False（否则上层误判未提交而重试，只会得到 nothing to
        # commit 的二次告警）；此时仅将 commit 置 None，不当异常收场。
        result["committed"] = True
        # 取哈希不用 rev-parse HEAD：commit 成功到读取 HEAD 之间有窗口，
        # daemon/dashboard 并发操作同一仓库时会记到别人的提交；本次提交恒触碰
        # paths，用 pathspec 限定的 log -1 锚定本次提交本身。
        try:
            rev = subprocess.run(
                ["git", "log", "-1", "--format=%H", "--"] + paths,
                cwd=str(proot),
                capture_output=True,
                text=True,
                timeout=_PROBE_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            return result
        result["commit"] = rev.stdout.strip() if rev.returncode == 0 else None
        return result
    except (OSError, subprocess.TimeoutExpired) as e:
        _unstage(proot, paths)
        return _fail(f"归档提交异常: {e}")


def _unstage(proot: Path, paths) -> None:
    """提交失败/异常后，把本次已写入索引的归档路径 reset 回滚（fail-open）。

    只 reset 本次 pathspec 范围，不动索引中其它无关 staged 内容；reset 自身
    失败时静默忽略（仅 best-effort），保证失败路径不在索引残留半状态。
    """
    try:
        subprocess.run(
            ["git", "reset", "--"] + paths,
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _has_tracked_files(proot: Path, pathspec: str) -> bool:
    """pathspec 下是否有 git 跟踪文件（判定删除侧是否需要参与提交）。"""
    try:
        r = subprocess.run(
            ["git", "ls-files", "--", pathspec],
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False

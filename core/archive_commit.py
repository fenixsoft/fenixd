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

import subprocess
from pathlib import Path

_PROBE_TIMEOUT = 30
_ADD_TIMEOUT = 60
_COMMIT_TIMEOUT = 120


def commit_archive_move(project_root, spec_name: str, archive_dir) -> dict:
    """提交一次归档移动（只 commit，不 push）。

    Args:
        project_root: 项目根目录
        spec_name: SPEC 名（用于提交信息）
        archive_dir: 移动后的归档目录路径（Path/str）

    Returns:
        {"committed": bool, "commit": str|null, "warning": str|null}
        - committed=True：提交成功，commit 为本次提交的全量 hash；
        - committed=False：warning 说明原因（非 git 仓库 / git 失败 / 无可提交内容）。
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
            return _fail(f"git commit 失败: {commit.stderr.strip() or f'exit {commit.returncode}'}")
        # 取哈希不用 rev-parse HEAD：commit 成功到读取 HEAD 之间有窗口，
        # daemon/dashboard 并发操作同一仓库时会记到别人的提交；本次提交恒触碰
        # paths，用 pathspec 限定的 log -1 锚定本次提交本身。
        rev = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--"] + paths,
            cwd=str(proot),
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
        result["committed"] = True
        result["commit"] = rev.stdout.strip() if rev.returncode == 0 else None
        return result
    except (OSError, subprocess.TimeoutExpired) as e:
        return _fail(f"归档提交异常: {e}")


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

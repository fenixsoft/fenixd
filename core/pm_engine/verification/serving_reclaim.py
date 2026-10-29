"""serving_reclaim.py — .fenix/verify-serving/ 目录与 boot.log 的生命周期回收。

reclaim_verify_serving D1/D2/D3/D5：

对 `.fenix/verify-serving/` 下每个 `<spec>-<ts>` 目录判定是否「无主」，
保留判据（spec 存活/登记/活进程/宽限期/在飞）全部满足 fail-safe
（异常时返回「保留」），回收动作通过
`git worktree remove --force` + `git worktree prune` 完成，幂等且
不触碰 `servers.json` / `contract_selfcheck.json` 等状态文件。

触发点（design D4）：
- daemon 启动 reconcile（use_in_flight=False）
- 600s 周期 orphan_clean 节拍（use_in_flight=True）

由 fenixd._reclaim_verify_serving_tree 调度，不依赖 VerificationPipeline 实例。
"""

import logging
import os
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path

import subprocess

from core.serving_registry import ServingRegistry

RECLAIM_GRACE_SECONDS = 600

_STATE_FILE_NAMES = frozenset({
    "servers.json",
    "servers.json.lock",
    "contract_selfcheck.json",
})


# ── 保留判据 helper ──────────────────────────────────────────────────────────


def parse_spec_from_worktree_name(name: str):
    """从目录名解析 spec 名：{spec}-{时间戳后缀}。

    末段须至少 10 位数字——秒级纪元 10 位、纳秒纪元 19 位均合法。
    code-review 78057677e669：serving.py 以 time.time_ns() 生成 19 位后缀，
    原「恰好 10 位」全等解析对现行命名恒返回 None——目录回收把全部现行
    命名判「无法归属」fail-safe 保留（reclaimed 恒空），boot.log 侧
    is_spec_registered_in_servers / has_live_process_for_spec 两道防误删
    保护随之静默失效。无法解析返回 None。
    spec 名自身可含连字符与数字后缀（如 evo-merge-back-wip-overlap-gate-575976）。
    """
    match = re.fullmatch(r"(.+)-(\d{10,})", name)
    if match is None:
        return None
    spec = match.group(1)
    if not spec:
        return None
    return spec


def is_spec_alive(spec: str, project_root: Path) -> bool:
    """判据 1：spec 存活于 spec/changes/ 或 spec/archive/<日期>-<spec>。

    archive 目录名形如 YYYY-MM-DD-<spec>（归档写点统一为
    f"{date.today().isoformat()}-{spec_name}"），按「剥离日期前缀后整段
    == spec」全等匹配。无法判定时返回 True（fail-safe）。
    """
    try:
        changes_dir = project_root / "spec" / "changes"
        if (changes_dir / spec).is_dir():
            return True
        archive_dir = project_root / "spec" / "archive"
        if archive_dir.is_dir():
            for entry in archive_dir.iterdir():
                if not entry.is_dir():
                    continue
                # 日期前缀剥离后整段全等（code-review 3178096202d1：原
                # endswith("-"+spec) 在 spec 名互为后缀组件时误命中——归档
                # 2026-01-01-add-spec-hooks 以 "-hooks" 结尾使已死 spec "hooks"
                # 被误判存活，其无主 serving worktree 与 boot.log 每轮被本判据
                # 保留，回收永不发生）；非日期前缀形态不归属本判据，失败方向
                # 仍是保守保留
                m = re.fullmatch(r"\d{4}-\d{2}-\d{2}-(.+)", entry.name)
                if m is not None and m.group(1) == spec:
                    return True
        return False
    except Exception:
        return True


def is_registered_in_servers(wt_path: Path, project_root: Path) -> bool:
    """判据 2：目录绝对路径在 servers.json 登记的 worktree 字段中。

    两侧均 Path.resolve() 后全等匹配。worktree 为空串的登记项不参与匹配
    （serving_registry.register 未传 wt_path 时写空串）。
    无法判定时返回 True（fail-safe）。
    """
    try:
        resolved = wt_path.resolve()
        for entry in ServingRegistry(project_root, logger=None).entries():
            registered_path = entry.get("worktree", "")
            if not registered_path:
                continue
            if Path(registered_path).resolve() == resolved:
                return True
        return False
    except Exception:
        return True


def has_live_process(wt_path: Path) -> bool:
    """判据 3：进程表存在 argv 或 cwd 指向该目录的存活进程。

    扫描 /proc/[pid]/cmdline 与 /proc/[pid]/cwd。
    无法判定时返回 True（fail-safe）。
    """
    try:
        target = str(wt_path.resolve())
        proc_base = Path("/proc")
        if not proc_base.is_dir():
            return True
        for pid_dir in proc_base.iterdir():
            pid_name = pid_dir.name
            if not pid_name.isdigit():
                continue
            # argv check（code-review f9dc60296502：与 cwd 判据同口径——cmdline
            # 按 NUL 切分成单个 argv 后做全等/目录前缀匹配；纯子串匹配在目录名
            # 互为前缀时误命中（…/spec-1000 命中指向 …/spec-10001 的进程），
            # 失效方向为 fail-safe 误保留、无主目录永不回收）
            cmdline_file = pid_dir / "cmdline"
            try:
                cmdline_bytes = cmdline_file.read_bytes()
                cmdline = cmdline_bytes.decode("utf-8", "replace")
                if any(
                    arg == target or arg.startswith(target + os.sep)
                    for arg in cmdline.split("\0")
                ):
                    return True
            except OSError:
                pass
            # cwd check
            cwd_file = pid_dir / "cwd"
            try:
                cwd_link = os.readlink(str(cwd_file))
                # code-review 4ac8ad87577c：readlink 结果先 realpath 归一再比较
                # （与 worktree_manager/locks.py 的 _pid_in_project_worktrees /
                # _kill_worktree_strays 同范式，消解符号链接/挂载拼写差异）——
                # 字面前缀匹配在 cwd 为拼写不同但同物理的路径时漏命中，失败
                # 方向是「判无主→删目录」而非保守保留
                cwd_real = os.path.realpath(cwd_link)
                # code-review 7eab5dba1293：分隔符与 argv 判据同源（os.sep），
                # 消除同函数两口径
                if cwd_real == target or cwd_real.startswith(target + os.sep):
                    return True
            except OSError:
                pass
        return False
    except Exception:
        return True


def is_within_grace_period(wt_path: Path) -> bool:
    """判据 4：目录 mtime 在宽限期内（RECLAIM_GRACE_SECONDS = 600）。

    无法判定时返回 True（fail-safe）。
    """
    try:
        mtime = wt_path.stat().st_mtime
        return (time.time() - mtime) < RECLAIM_GRACE_SECONDS
    except Exception:
        return True


def is_spec_registered_in_servers(spec: str, project_root: Path) -> bool:
    """判据 2（spec 前缀匹配，boot.log 维度）：servers.json 存在 worktree
    目录名解析为该 spec 的登记项。

    boot.log 无对应目录可做路径全等匹配（is_registered_in_servers），
    退而按登记 worktree 名 {spec}-{时间戳后缀}（≥10 位数字，与
    parse_spec_from_worktree_name 同一契约）解析出 spec 后比对。
    无法判定时返回 True（fail-safe）。
    """
    try:
        for entry in ServingRegistry(project_root, logger=None).entries():
            registered_path = entry.get("worktree", "")
            if not registered_path:
                continue
            if parse_spec_from_worktree_name(Path(registered_path).name) == spec:
                return True
        return False
    except Exception:
        return True


def has_live_process_for_spec(spec: str, project_root: Path) -> bool:
    """判据 3（spec 前缀匹配，boot.log 维度）：存在 argv/cwd 指向该 spec
    serving worktree 的活进程（孤儿进程仍在写 boot.log 的场景）。

    serve_root 下目录名解析为该 spec 的目录逐个复用 has_live_process。
    无法判定时返回 True（fail-safe）。
    """
    try:
        serve_root = Path(project_root) / ".fenix" / "verify-serving"
        if not serve_root.is_dir():
            return False
        for entry in serve_root.iterdir():
            if not entry.is_dir():
                continue
            if parse_spec_from_worktree_name(entry.name) == spec and has_live_process(entry):
                return True
        return False
    except Exception:
        return True


def _should_keep_scoped(
    spec_name: str | None,
    project_root: Path,
    grace_target: Path,
    keep_registered: Callable[[], bool],
    keep_live_process: Callable[[], bool],
    is_spec_in_flight=None,
) -> bool:
    """保留判据聚合（参数化变体）：判据顺序与 fail-safe 语义的单一来源。

    登记在册/活进程两判据的匹配维度由调用方注入（零参谓词，自带 fail-safe、
    无法判定时返回 True）：目录回收按路径全等（is_registered_in_servers /
    has_live_process），boot.log 回收按 spec 解析（is_spec_registered_in_servers
    / has_live_process_for_spec）。spec 存活/宽限期/在飞判据两维共用，避免判据
    链在目录与 boot.log 两处手工内联漂移。
    """
    # 判据 1：spec 存活
    if spec_name is not None and is_spec_alive(spec_name, project_root):
        return True
    # 判据 2：登记在册
    if keep_registered():
        return True
    # 判据 3：活进程
    if keep_live_process():
        return True
    # 判据 4：宽限期内
    if is_within_grace_period(grace_target):
        return True
    # 判据 5：spec 验证在飞（可选；无法判定时 fail-safe 保留）
    if is_spec_in_flight is not None and spec_name is not None:
        try:
            if is_spec_in_flight(spec_name):
                return True
        except Exception:
            return True
    return False


def _should_keep(
    spec_name: str | None,
    wt_path: Path,
    project_root: Path,
    is_spec_in_flight=None,
) -> bool:
    """保留判据聚合：满足任一即保留（is_spec_in_flight 命中亦保留）。

    目录维度（路径全等匹配），注入维度判定后委托 _should_keep_scoped。
    """
    return _should_keep_scoped(
        spec_name,
        project_root,
        wt_path,
        keep_registered=lambda: is_registered_in_servers(wt_path, project_root),
        keep_live_process=lambda: has_live_process(wt_path),
        is_spec_in_flight=is_spec_in_flight,
    )


# ── 回收执行 ─────────────────────────────────────────────────────────────────


def _remove_serving_worktree(project_root: Path, wt_path: Path, logger=None) -> None:
    """git worktree remove --force + git worktree prune（幂等）。

    logger: 可选 fenix 风格日志记录器（(component, message) 接口）。注入时
    两条收尾 prune 告警与其余回收日志走同一通道（同一轮回收的观测记录不拆
    sink）；缺省 None 回落 std logging（保持独立调用兼容）。

    git 非零返回（权限/文件被占用/路径非注册 worktree 等）时：先
    `git worktree prune` 清理失效登记再重试一次 remove——覆盖 git worktree
    add 中途失败遗留的普通目录、.git 文件损坏/缺失目录等非注册形态的残留；
    仍失败且调用方已过五连保留判据（确无主）时降级为对目录本体的受控删除
    （shutil.rmtree），避免残留永久滞留且每周期重复告警。全部手段均失败才抛
    RuntimeError（含 stderr 留痕），由调用方记 WARNING 且不计入 reclaimed，
    避免目录删除失败仍被记为回收成功。删除动作已成功时，收尾 prune 的失败
    仅记 WARNING 照常返回（只影响 git 登记簿清理，不影响回收结果）。
    """

    def _git_remove():
        return subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "worktree",
                "remove",
                "--force",
                str(wt_path),
            ],
            capture_output=True,
            text=True,
            # code-review item dbe9a23549a6：固化解码口径（对齐
            # serving.py._remove_serving_worktree 同款写点）——text=True
            # 缺省按 locale strict 解码，git 输出（含怪异文件名的 worktree
            # 路径报错）混入非 UTF-8 字节时抛 UnicodeDecodeError（ValueError
            # 子类），不在下方 except (OSError, SubprocessError) 捕获清单内，
            # 击穿「异常面归一（调用方只见 RuntimeError）」契约（下方两次
            # prune 同口径）
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    try:
        remove = _git_remove()
        if remove.returncode != 0:
            subprocess.run(
                ["git", "-C", str(project_root), "worktree", "prune"],
                capture_output=True,
                text=True,
                # code-review item dbe9a23549a6：同 _git_remove 固化解码口径
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            remove = _git_remove()
    except (OSError, subprocess.SubprocessError) as exc:
        # 异常面归一（code-review item d9eee63197c5）：git 缺失（OSError）与
        # remove/prune 超时（TimeoutExpired）同样按「全部手段均失败才抛
        # RuntimeError」的文档契约折算（附上下文），调用方只见 RuntimeError、
        # 不必细分 subprocess 异常族。
        raise RuntimeError(
            f"git worktree remove --force {wt_path} 基础设施失败: {exc}"
        ) from exc
    if remove.returncode != 0:
        try:
            shutil.rmtree(wt_path)
        except Exception as rmtree_err:
            raise RuntimeError(
                f"git worktree remove --force {wt_path} 失败 "
                f"(rc={remove.returncode}): "
                f"{(remove.stderr or remove.stdout).strip()}；"
                f"prune 后重试仍失败，降级 rmtree 也失败: {rmtree_err}"
            ) from rmtree_err
    # 目录本体已删除成功，收尾 prune 只影响 git 登记簿清理：失败（非零返回码
    # 或异常）降级为 WARNING 照常返回，保证调用方 reclaimed 记账与实际删除
    # 结果一致（code-review be503d93b86f）。
    try:
        prune = subprocess.run(
            ["git", "-C", str(project_root), "worktree", "prune"],
            capture_output=True,
            text=True,
            # code-review item dbe9a23549a6：同 _git_remove 固化解码口径
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except Exception as prune_err:
        msg_tpl = (
            "serving_reclaim: 目录 %s 已删除但收尾 git worktree prune 异常"
            "（仅影响登记簿清理，不影响回收结果）: %s"
        )
        msg_args = (wt_path, prune_err)
        if logger is not None:
            logger.warning("serving_reclaim", msg_tpl % msg_args)
        else:
            logging.getLogger("fenixd.serving_reclaim").warning(msg_tpl, *msg_args)
        return
    if prune.returncode != 0:
        msg_tpl = (
            "serving_reclaim: 目录 %s 已删除但收尾 git worktree prune 失败 "
            "(rc=%s)（仅影响登记簿清理，不影响回收结果）: %s"
        )
        msg_args = (
            wt_path,
            prune.returncode,
            (prune.stderr or prune.stdout).strip(),
        )
        if logger is not None:
            logger.warning("serving_reclaim", msg_tpl % msg_args)
        else:
            logging.getLogger("fenixd.serving_reclaim").warning(msg_tpl, *msg_args)


def _is_boot_log_target(name: str) -> bool:
    """判断文件名是否为可解析的 <spec>-boot.log（不含时间戳后缀）。"""
    if not name.endswith("-boot.log"):
        return False
    spec = name[: -len("-boot.log")]
    return bool(spec)


def _boot_log_spec(name: str) -> str:
    """从 <spec>-boot.log 剥离后缀得到 spec 名（boot.log 不含时间戳）。"""
    return name[: -len("-boot.log")]


def _is_state_file(name: str) -> bool:
    """判断文件名是否为必须保留的顶层状态文件。"""
    return name in _STATE_FILE_NAMES


# ── 公开入口 ─────────────────────────────────────────────────────────────────


def reclaim_verify_serving(
    project_root,
    logger=None,
    is_spec_in_flight=None,
    reclaim_enabled: bool = True,
) -> dict:
    """serving worktree 与 boot.log 无主回收。

    Args:
        project_root: 项目根目录。
        logger: 可选日志记录器（须有 .info/.warning 方法）。
        is_spec_in_flight: callable(spec_name) -> bool，判定 spec 是否在飞
            （验证活跃）。为 None 时所有 spec 视为非在飞。
        reclaim_enabled: verify.serving_reclaim.enabled 开关值。
            False 时早退（MUST NOT 调 git、MUST NOT 删除任何文件）。

    Returns:
        {"reclaimed": [...], "kept": [...], "boot_logs_reclaimed": [...]}
    """
    if not reclaim_enabled:
        if logger:
            logger.info("serving_reclaim", "verify.serving_reclaim.enabled=false，跳过目录回收")
        return {"reclaimed": [], "kept": [], "boot_logs_reclaimed": []}

    project_root = Path(project_root)
    serve_root = project_root / ".fenix" / "verify-serving"
    if not serve_root.is_dir():
        return {"reclaimed": [], "kept": [], "boot_logs_reclaimed": []}

    reclaimed = []
    kept = []
    boot_logs_reclaimed = []

    # ── 目录回收 ──
    for entry in sorted(serve_root.iterdir()):
        if not entry.is_dir():
            continue
        spec_name = parse_spec_from_worktree_name(entry.name)
        if spec_name is None:
            # 目录名不符合 {spec}-{时间戳后缀} 约定：无法判定归属，fail-safe 保留
            kept.append(entry.name)
            continue
        if _should_keep(spec_name, entry, project_root, is_spec_in_flight):
            kept.append(entry.name)
            continue
        # 无主 → 回收
        try:
            _remove_serving_worktree(project_root, entry, logger)
            reclaimed.append(entry.name)
            if logger:
                logger.info(
                    "serving_reclaim",
                    f"回收无主 serving worktree: {entry.name}",
                )
        except Exception as e:
            # code-review item 42deb4eb7182：回收失败目录计入 kept 留痕
            # （与无法判定归属 fail-safe 保留同口径，同属「本轮未回收」观测
            # 集合），保证返回值对 serve_root 目录全集完备，消费方按返回值
            # 对账时不必翻日志才发现回收缺口
            kept.append(entry.name)
            if logger:
                logger.warning(
                    "serving_reclaim",
                    f"回收 serving worktree 失败（继续）: {entry.name}: {e}",
                )

    # ── boot.log 回收 ──
    for file_entry in sorted(serve_root.iterdir()):
        if not file_entry.is_file():
            continue
        name = file_entry.name
        # 顶层状态文件一律保留
        if _is_state_file(name):
            continue
        # 无法解析为 <spec>-boot.log → 保留（杂散文件计入 kept 留痕观测）
        if not _is_boot_log_target(name):
            kept.append(name)
            continue
        log_spec = _boot_log_spec(name)
        # 与目录回收同一保留口径（判据链复用 _should_keep_scoped，fail-safe）：
        # spec 存活/登记在册/活进程/宽限期内/在飞任一命中即保留，防 spec 已消失
        # 但实例仍存活或登记在册时误删正在写入的证据日志。匹配维度为 spec 解析
        # （is_spec_registered_in_servers / has_live_process_for_spec），以零参
        # 谓词注入。
        if _should_keep_scoped(
            log_spec,
            project_root,
            file_entry,
            keep_registered=lambda: is_spec_registered_in_servers(log_spec, project_root),
            keep_live_process=lambda: has_live_process_for_spec(log_spec, project_root),
            is_spec_in_flight=is_spec_in_flight,
        ):
            # 判据命中保留：同样计入 kept 留痕（与目录维度口径对齐）
            kept.append(name)
            continue
        # 无主 → 删除
        try:
            file_entry.unlink()
            boot_logs_reclaimed.append(name)
            if logger:
                logger.info("serving_reclaim", f"回收无主 boot.log: {name}")
        except Exception as e:
            # code-review item f1092ccd9c85：回收失败文件计入 kept 留痕
            # （与目录维度回收失败留痕同口径，同属「本轮未回收」观测集合），
            # 保证返回值对 boot.log 全集完备，消费方按返回值对账时不必翻日志。
            kept.append(name)
            if logger:
                logger.warning(
                    "serving_reclaim",
                    f"回收 boot.log 失败（继续）: {name}: {e}",
                )

    # ── 观测性日志 ──
    if logger:
        logger.info(
            "serving_reclaim",
            f"serving 回收完成：reclaimed={len(reclaimed)}，"
            f"kept={len(kept)}，boot_logs_reclaimed={len(boot_logs_reclaimed)}",
        )

    return {
        "reclaimed": reclaimed,
        "kept": kept,
        "boot_logs_reclaimed": boot_logs_reclaimed,
    }

"""self_update_apply.py — 框架与 dsh-plugins 更新应用编排（分离进程）。

add-auto-update SPEC 应用侧（design D4 核心决策）：更新应用 MUST NOT 由
daemon 或 dashboard 进程内执行——三段式「停 daemon」会杀死编排者自身。
触发方（dashboard API / CLI ``bin/fenix_update.py apply``）经 ``spawn_apply``
拉起一个**平台化分离的短命编排进程**（POSIX setsid / Windows DETACHED_
PROCESS 均由 PAL ``pal.spawn_detached`` 单点承载），编排进程独立完成
下载→校验→staging→停服务→换装→起服务→状态落盘，进度/结果全程写
``~/.fenix/update/status.json``，UI 轮询读。

换装语义（design D5）：停**全部服务化进程**（N 个项目 daemon unit 经 PAL
D 组 start/stop/is_running 项目根单源 + dashboard unit）→ 旧根 rename 为
``<原名>.old-<ts>`` → staging 就位为框架根（**路径不变**——既有项目骨架
链接全部继续有效）→ 按 stop 逆序起。任一步失败回滚；成功后仅保留一代
回滚副本。在飞 run 预检不过 → 拒绝换装。

插件更新（design D6）与框架更新相互独立：单边失败不阻断另一边。

平台纪律：零直接平台分支（``pal.IS_WINDOWS``/PAL D 组承载）；目录 rename
目标恒不存在（Windows 替换写纪律的合法形态）；原子写收口 fs_utils。
"""

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tarfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from core.platform import api as pal
from core.self_update import (
    APPLY_LOCK_PATH,
    APPLY_LOCK_STALE_S,
    APPLY_PHASE_FAILED,
    APPLY_PHASE_QUEUED,
    APPLY_PHASE_RUNNING,
    APPLY_PHASE_SUCCESS,
    AUDITS_PATH,
    FORM_ARTIFACT,
    FORM_SOURCE,
    PLUGINS_REPO,
    QUERY_TIMEOUT_S,
    STATUS_PATH,
    UPDATE_DIR,
    UpdateConfig,
    UpdateLock,
    append_audit,
    apply_mirror_url,
    detect_plugins_state,
    fetch_latest_release,
    load_update_config,
    mark_apply_phase,
    read_framework_version,
    read_status,
)

logger = logging.getLogger("fenixd.self_update_apply")

# 三段式停服务后的排水等待上界（秒）：supervisor 排水典型秒级，120s 覆盖
# 既有 stop 双轨的 ≤30s 轮询预算裕量；超时未停记入结果仍继续（rename 若因
# 占用失败自然走回滚路径——Windows 占用失败是确定性失败，不是静默损坏）。
STOP_DRAIN_TIMEOUT_S = 120.0
STOP_POLL_INTERVAL_S = 2.0

# 在飞 run 判定的空闲上界（秒）：runs/*.jsonl 非归档且 mtime 在 6h 内判在飞。
# daemon 每 300s 把终态 run 移入 archive/（runs retention），6h 无写入的
# 非归档 run 记录只能是崩溃残留（误锁更新的死锁防线）；活跃 run 持续写
# 事件流，6h 静默的「活跃」run 不存在。
RUN_INFLIGHT_MAX_IDLE_S = 6 * 3600

# dsh CLI 单次调用超时（秒）：plugin remove/add 是本地 profile 文件操作，
# 120s 覆盖 pnpm workspace 依赖树改写。
DSH_CLI_TIMEOUT_S = 120.0

# 制品完整性断言清单（逐字对齐 scripts/package.sh 既有清单——运行期硬读面，
# 缺一即半残制品，2.2 任务口径「缺一即失败进回滚」）
INTEGRITY_REQUIRED = (
    "fenix-init",
    "fenixd.py",
    "install.sh",
    "install.ps1",
    "README.md",
    "VERSION",
    ".fenix/config.template.yaml",
    ".fenix/config.user.template.yaml",
    "bin/fenixd_supervisor.py",
    "bin/dsh_acceptance.py",
    "bin/fenix_dashboard.py",
    "bin/fenix_spec.py",
    "agents/implementer.md",
    "agents/verifier.md",
    "templates/gitignore-fenix.txt",
    "templates/STATE.md",
    "templates/PROJECT_LOG.md",
    "skills/fenix-new/SKILL.md",
    "core/dashboard/static/dist/index.html",
    "dsh-bundle/dist/index.js",
    "dsh-bundle/dist/session-tidy-helper.mjs",
    "schemas/spec-driven/schema.yaml",
    "schemas/spec-driven/templates/tasks.md",
    "vendor/floorplan/SKILL.md",
    "vendor/floorplan/scripts/scan.mjs",
    "vendor/floorplan/scripts/build.mjs",
    "vendor/floorplan/scripts/lib/common.mjs",
)

# 桌面版手动更新文档指引（desktop profile 检出降级，design D6）
DESKTOP_GUIDE = (
    "desktop profile 由 Electron 桌面版专属管理（CLI 不可改写），请按 "
    "docs/install.md §6c「desktop profile 专用装配路径」手动更新桌面版插件"
)


class ApplyError(Exception):
    """编排失败（阶段名随异常携带，供状态落盘定位失败阶段）。"""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


# ── 2.1 分离编排进程入口 ───────────────────────────────────────────────


def spawn_apply(
    *,
    framework_root=None,
    source: str = "dashboard",
    status_path=None,
    apply_lock_path=None,
) -> dict:
    """触发方入口：占锁 → 状态记 queued → 拉起分离编排进程 → 立即返回受理。

    Returns: ``{"ok": True, "pid": <编排进程 pid>}`` 或
    ``{"ok": False, "conflict": True, "error": <可读原因>}``（apply.lock
    被占 / 编排已在进行中——调用方映射 409）。

    互斥时序（design D5 风险面「多项目 daemon 并发触发竞态」）：触发方持
    apply.lock 完成「queued 状态写入」后再释放——queued 落盘先于响应返回，
    并发第二触发者在锁竞争或 phase 判读上必然落 409；编排进程启动后自取
    该锁（陈锁清扫兜底触发方崩溃残留）。
    """
    root = Path(framework_root) if framework_root else _default_framework_root()
    spath = Path(status_path) if status_path else STATUS_PATH
    lpath = Path(apply_lock_path) if apply_lock_path else APPLY_LOCK_PATH
    lock = UpdateLock(lpath, APPLY_LOCK_STALE_S)
    if not lock.acquire():
        return {"ok": False, "conflict": True,
                "error": "已有更新编排进行中（apply.lock 被占）"}
    try:
        st = read_status(spath) or {}
        phase = (st.get("apply") or {}).get("phase")
        if phase in (APPLY_PHASE_QUEUED, APPLY_PHASE_RUNNING):
            return {"ok": False, "conflict": True,
                    "error": f"更新编排已在进行中（phase={phase}）"}
        mark_apply_phase(
            APPLY_PHASE_QUEUED,
            {"trigger": source, "queued_at": _utcnow_iso()},
            status_path=spath,
        )
    finally:
        lock.release()
    cmd = [sys.executable, "-m", "core.self_update_apply",
           "--framework-root", str(root), "--source", source]
    try:
        proc = pal.spawn_detached(cmd, cwd=str(root))
    except Exception as e:  # noqa: BLE001 — spawn 失败回滚 queued 占位
        mark_apply_phase(
            APPLY_PHASE_FAILED,
            {"trigger": source, "error": f"编排进程拉起失败: {e}"},
            status_path=spath,
        )
        return {"ok": False, "conflict": False, "error": f"编排进程拉起失败: {e}"}
    return {"ok": True, "pid": getattr(proc, "pid", None)}


def _default_framework_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _utcnow_iso() -> str:
    from core.timelib import now_utc, to_storage

    return to_storage(now_utc())


# ── 编排上下文与注入缝 ─────────────────────────────────────────────────


@dataclass
class ApplyContext:
    """编排上下文：路径配置 + 测试注入缝（stop/start/registry/dsh 全可注入）。"""

    framework_root: Path
    source: str = "manual"
    update_dir: Path = UPDATE_DIR
    profiles_dir: Optional[Path] = None  # None → resolve_dsh_home()/profiles
    target: Optional[str] = None  # 指定目标 tag；缺省读检查状态 remote
    status_path: Optional[Path] = None
    audits_path: Optional[Path] = None
    apply_lock_path: Optional[Path] = None
    config: Optional[UpdateConfig] = None
    # 注入缝（缺省 None = 走真实实现）
    http_get: Optional[Callable] = None
    download_impl: Optional[Callable] = None  # (url, dest_path) -> None
    project_roots_fn: Optional[Callable] = None  # () -> list[Path]
    stop_units_fn: Optional[Callable] = None  # (daemon_roots, dashboard) -> dict
    start_units_fn: Optional[Callable] = None  # (daemon_roots, dashboard) -> dict
    dsh_runner: Optional[Callable] = None  # (argv) -> (rc, stdout, stderr)
    drain_poll_fn: Optional[Callable] = None  # (daemon_roots) -> list[仍活跃]
    # 服务化目标注入缝（测试三段式不触真实 systemd；缺省走 collect_hosted_targets）
    injected_daemon_roots: Optional[list] = None
    injected_dashboard: Optional[bool] = None
    stages: list = field(default_factory=list)
    # 运行期状态（rollback_swap 记录回滚结果，终态统一写点消费）
    rollback_info: Optional[dict] = None
    recovered_staging: Optional[Path] = None

    def resolved_status_path(self) -> Path:
        return self.status_path or (self.update_dir / "status.json")

    def resolved_audits_path(self) -> Path:
        return self.audits_path or (self.update_dir / "audits.jsonl")

    def resolved_apply_lock_path(self) -> Path:
        return self.apply_lock_path or (self.update_dir / "apply.lock")

    def record_stage(self, stage: str, ok: bool, detail: str = "") -> None:
        """阶段推进即落盘 status.apply.stages（每步完成即更新，design D5）。"""
        self.stages.append({"stage": stage, "ok": ok, "detail": detail,
                            "ts": _utcnow_iso()})
        mark_apply_phase(
            APPLY_PHASE_RUNNING,
            {"trigger": self.source, "stages": list(self.stages)},
            status_path=self.resolved_status_path(),
        )


# ── 2.3 在飞 run 预检与项目枚举 ────────────────────────────────────────


def registered_project_roots(framework_root=None) -> list:
    """编排面项目枚举：dashboard registry 显式注册项目 + 框架根自身。

    registry 读失败降级为「仅框架根」——预检宁漏报不误伤（漏报的代价是
    少停一个 unit，rename 失败走回滚路径；误报的代价是拒绝合法更新）。
    """
    root = Path(framework_root) if framework_root else _default_framework_root()
    roots = [root]
    try:
        from core.dashboard.registry import Registry

        for p in Registry().list_projects():
            path = p.get("path") if isinstance(p, dict) else None
            if not path:
                continue
            rp = Path(path)
            if rp.exists() and rp not in roots:
                roots.append(rp)
    except Exception as e:  # noqa: BLE001 — registry 不可用降级
        logger.debug("apply: registry 项目枚举失败（降级仅框架根）: %s", e)
    return roots


def find_inflight_runs(project_roots, *, max_idle_s: float = RUN_INFLIGHT_MAX_IDLE_S,
                       now_ts: Optional[float] = None) -> list:
    """在飞 run 判定（2.3）：各项目 ``.fenix/runs/*.jsonl`` 非归档记录。

    以活跃 run **记录**判读（任务口径：勿依赖 dashboard active_runs 计数——
    历史实测该计数不可信）；mtime 超过 max_idle_s 的记录视为崩溃残留不算
    在飞。Returns: ``[{"project": Path, "run": Path, "idle_s": float}]``。
    """
    moment = now_ts if now_ts is not None else time.time()
    inflight = []
    for proot in project_roots:
        runs_dir = Path(proot) / ".fenix" / "runs"
        try:
            entries = list(runs_dir.glob("*.jsonl"))
        except OSError:
            continue
        for run_file in entries:
            try:
                idle = moment - run_file.stat().st_mtime
            except OSError:
                continue
            if 0 <= idle <= max_idle_s:
                inflight.append({"project": Path(proot), "run": run_file,
                                 "idle_s": round(idle, 1)})
    return inflight


# ── 2.2 下载 / 校验 / staging ─────────────────────────────────────────


def _download_file(url: str, dest: Path,
                   download_impl: Optional[Callable] = None) -> Path:
    """下载制品到 dest（流式落盘；注入缝供测试假资产）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if download_impl is not None:
        download_impl(url, dest)
        return dest
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "fenixd-self-update"})
    with urllib.request.urlopen(req, timeout=max(QUERY_TIMEOUT_S, 300)) as resp, \
            open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
    return dest


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _parse_sha256sum(text: str) -> dict:
    """sha256sum 输出解析：``{filename: hash}``（package.sh 双行形态单点）。"""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            name = parts[1].strip().lstrip("*")
            out[name] = parts[0].lower()
    return out


def _fetch_expected_sha256(
    release,  # ReleaseInfo
    asset_name: str,
    *,
    mirror: str = "",
    http_get: Optional[Callable] = None,
    download_impl: Optional[Callable] = None,
    workdir: Optional[Path] = None,
) -> str:
    """取制品期望 sha256：``<包名>.sha256`` 双行取对应行，``<资产名>.sha256`` 兜底。

    package.sh 实际产物为 ``fenixd-<v>.sha256`` 单文件双行（同时含 tar.gz
    与 zip 两行）；找不到包名级文件时按资产级 ``<asset>.sha256`` 兜底探测
    （任务 2.2 口径）。
    """
    getter = http_get or (lambda url, headers=None, timeout_s=30.0: _http_get_bytes(url))
    pkg_name = asset_name
    for suffix in (".tar.gz", ".zip"):
        if asset_name.endswith(suffix):
            pkg_name = asset_name[: -len(suffix)]
            break
    candidates = [f"{pkg_name}.sha256", f"{asset_name}.sha256"]
    workdir = Path(workdir) if workdir else Path(os.environ.get("TMPDIR", "/tmp"))
    for cand_name in candidates:
        url = release.assets.get(cand_name)
        if not url:
            continue
        status, body = getter(apply_mirror_url(url, mirror))
        if status != 200 or not body:
            continue
        mapping = _parse_sha256sum(body.decode("utf-8", errors="replace"))
        if asset_name in mapping:
            return mapping[asset_name]
        # 单资产文件形态：文件内容可能是裸 hash 或 hash+文件名
        if len(mapping) == 1:
            return next(iter(mapping.values()))
        first_line = body.decode("utf-8", errors="replace").strip().splitlines()[0]
        token = first_line.split()[0].strip().lower()
        if len(token) == 64:
            return token
    raise ApplyError("verify", f"制品校验文件缺失：{candidates} 均不可得")


def _http_get_bytes(url: str, headers: Optional[dict] = None,
                    timeout_s: float = 30.0) -> "tuple[int, bytes]":
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": "fenixd-self-update",
                                               **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return int(resp.status), resp.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:  # noqa: BLE001
            body = b""
        return int(e.code), body


def download_and_verify(
    release,  # ReleaseInfo
    asset_name: str,
    dest_dir: Path,
    *,
    mirror: str = "",
    http_get: Optional[Callable] = None,
    download_impl: Optional[Callable] = None,
) -> Path:
    """下载资产 + sha256 强校验（失败即中止，本地安装零改动，spec 硬门）。"""
    url = release.assets.get(asset_name)
    if not url:
        raise ApplyError("download", f"release 资产缺失: {asset_name}")
    dest = Path(dest_dir) / asset_name
    _download_file(apply_mirror_url(url, mirror), dest,
                   download_impl=download_impl)
    expected = _fetch_expected_sha256(
        release, asset_name, mirror=mirror, http_get=http_get,
        download_impl=download_impl, workdir=dest_dir,
    )
    actual = _sha256_of(dest)
    if actual.lower() != expected.lower():
        try:
            dest.unlink()
        except OSError:
            pass
        raise ApplyError(
            "verify",
            f"sha256 校验失败（{asset_name}）：期望 {expected}，实际 {actual}"
            "——下载制品已删除，本地安装未改动",
        )
    return dest


def _safe_archive_members(names) -> bool:
    """归档成员路径安全校验：拒绝绝对路径与 ``..`` 穿越（对抗性制品防线）。"""
    for name in names:
        if name.startswith("/") or name.startswith("\\"):
            return False
        parts = name.replace("\\", "/").split("/")
        if ".." in parts:
            return False
    return True


def extract_to_staging(archive: Path, staging_base: Path) -> Path:
    """解压制品到 staging，返回内容根目录（tar/zip 顶层单目录）。

    目录 rename 的同盘原子性依赖 staging 与框架根同级（design D5）——
    staging_base 调用方保证为框架根 parent 下的
    ``fenixd-update-staging-<ts>``。
    """
    staging_base = Path(staging_base)
    staging_base.mkdir(parents=True, exist_ok=True)
    name = str(archive)
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(archive, "r:gz") as tf:
            members = tf.getnames()
            if not _safe_archive_members(members):
                raise ApplyError("staging", "制品归档含不安全路径（绝对路径/..），拒绝解压")
            tf.extractall(staging_base)
    elif name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            if not _safe_archive_members(zf.namelist()):
                raise ApplyError("staging", "制品归档含不安全路径（绝对路径/..），拒绝解压")
            zf.extractall(staging_base)
    else:
        raise ApplyError("staging", f"不支持的制品形态: {archive.name}")
    entries = [p for p in staging_base.iterdir() if p.is_dir()]
    if len(entries) != 1:
        raise ApplyError("staging",
                         f"制品顶层目录形态异常（期望单目录，得 {len(entries)} 个）")
    return entries[0]


def assert_integrity(content_root: Path) -> None:
    """制品完整性断言：package.sh 清单逐项硬读面在位（缺一即失败）。"""
    root = Path(content_root)
    missing = [req for req in INTEGRITY_REQUIRED if not (root / req).exists()]
    if missing:
        raise ApplyError(
            "staging",
            f"staging 完整性断言拦截（{len(missing)} 项缺失）：{missing[:5]}…"
            if len(missing) > 5 else
            f"staging 完整性断言拦截（{len(missing)} 项缺失）：{missing}",
        )


# ── 2.4 三段式换装（宿主操作真实实现）────────────────────────────────


def collect_hosted_targets(project_roots) -> "tuple[list, bool]":
    """枚举当前活跃的服务化进程：项目 daemon 根列表 + dashboard unit 在位否。

    Linux systemd 承载经 pal D 组 is_running（unit_active 单源）；dashboard
    unit 为 systemd 专属承载（Windows NSSM 后端无 dashboard 服务），经
    systemctl_available + unit_installed + unit_active 判定。全部判定失败
    降级为「未服务化」（跳过停步并在结果注明，spec 口径）。
    """
    daemon_roots = []
    for proot in project_roots:
        try:
            if pal.is_running(proot):
                daemon_roots.append(Path(proot))
        except Exception:  # noqa: BLE001 — 未服务化/无 systemd：跳过该根
            continue
    dashboard_hosted = False
    try:
        from core.systemd_hosting import (
            DASHBOARD_UNIT,
            systemctl_available,
            unit_active,
            unit_installed,
        )

        dashboard_hosted = (
            systemctl_available()
            and unit_installed(DASHBOARD_UNIT)
            and unit_active(DASHBOARD_UNIT)
        )
    except Exception:  # noqa: BLE001
        dashboard_hosted = False
    return daemon_roots, bool(dashboard_hosted)


def _default_stop_units(daemon_roots, dashboard_hosted) -> dict:
    """停全部服务化进程：项目 daemon 经 pal.stop（双平台单源）+ dashboard unit。"""
    errors = []
    for proot in daemon_roots:
        try:
            pal.stop(proot)
        except Exception as e:  # noqa: BLE001
            errors.append(f"stop {proot.name}: {e}")
    if dashboard_hosted:
        try:
            from core.systemd_hosting import DASHBOARD_UNIT, stop_unit_no_block

            stop_unit_no_block(DASHBOARD_UNIT)
        except Exception as e:  # noqa: BLE001
            errors.append(f"stop dashboard: {e}")
    return {"errors": errors}


def _default_start_units(daemon_roots, dashboard_hosted) -> dict:
    """按 stop 逆序起全部 unit：dashboard 先、项目 daemon 后（pal.start 单源）。"""
    errors = []
    if dashboard_hosted:
        try:
            from core.systemd_hosting import DASHBOARD_UNIT, start_unit_no_block

            start_unit_no_block(DASHBOARD_UNIT)
        except Exception as e:  # noqa: BLE001
            errors.append(f"start dashboard: {e}")
    for proot in daemon_roots:
        try:
            pal.start(proot)
        except Exception as e:  # noqa: BLE001
            errors.append(f"start {proot.name}: {e}")
    return {"errors": errors}


def _default_drain_poll(daemon_roots) -> list:
    """轮询排水：超时仍未活跃停止的 daemon 根列表（bounded，STOP_DRAIN_TIMEOUT_S）。"""
    deadline = time.monotonic() + STOP_DRAIN_TIMEOUT_S
    while time.monotonic() < deadline:
        still = []
        for proot in daemon_roots:
            try:
                if pal.is_running(proot):
                    still.append(proot)
            except Exception:  # noqa: BLE001
                continue
        if not still:
            return []
        time.sleep(STOP_POLL_INTERVAL_S)
    still = []
    for proot in daemon_roots:
        try:
            if pal.is_running(proot):
                still.append(proot)
        except Exception:  # noqa: BLE001
            continue
    return still


def swap_in_place(
    ctx: ApplyContext,
    staging_content: Path,
) -> dict:
    """三段式换装：停全部服务化进程 → 旧根 rename → staging 就位 → 逆序起。

    任一步失败抛 ApplyError（stage 标明失败阶段）——回滚由调用方
    ``rollback_swap`` 执行。目录 rename 目标恒不存在（Windows 替换写纪律
    唯一合法形态：摘除到唯一临时名 / 摘出旧根后空位就位）。
    """
    root = ctx.framework_root
    parent = root.parent
    ts = time.strftime("%Y%m%d-%H%M%S")
    old_dir = parent / f"{root.name}.old-{ts}"
    daemon_roots = getattr(ctx, "_daemon_roots", None)
    if daemon_roots is None:
        daemon_roots = list(ctx.injected_daemon_roots or [])
    dashboard_hosted = getattr(ctx, "_dashboard_hosted", None)
    if dashboard_hosted is None:
        dashboard_hosted = bool(ctx.injected_dashboard)

    # ① 停全部服务化进程（未服务化场景跳过停步并在结果注明）
    if ctx.stop_units_fn is not None:
        stop_result = ctx.stop_units_fn(daemon_roots, dashboard_hosted)
    else:
        stop_result = _default_stop_units(daemon_roots, dashboard_hosted)
    if not daemon_roots and not dashboard_hosted:
        stop_result["note"] = "未服务化场景（无活跃 unit）：跳过停步"
    still = None
    if ctx.drain_poll_fn is not None:
        still = ctx.drain_poll_fn(daemon_roots)
    else:
        still = _default_drain_poll(daemon_roots)
    if still:
        stop_result["still_running"] = [str(p) for p in still]
    if stop_result.get("errors") or stop_result.get("still_running"):
        raise ApplyError(
            "stop",
            f"停服务失败：errors={stop_result.get('errors')} "
            f"still_running={stop_result.get('still_running')}",
        )
    ctx.record_stage("stop", True, json.dumps(
        {"daemons": [str(p) for p in daemon_roots],
         "dashboard": dashboard_hosted,
         "note": stop_result.get("note", "")}, ensure_ascii=False))

    # ② 旧根 rename 为回滚副本（同盘 rename 原子；目标必不存在）
    try:
        os.rename(root, old_dir)
    except OSError as e:
        raise ApplyError("swap", f"旧根 rename 失败（占用未排净？）: {e}") from e
    ctx.record_stage("swap", True, f"旧根已保留为 {old_dir.name}")

    # ③ staging 就位为框架根（路径不变——既有项目骨架链接全部继续有效）
    try:
        os.rename(staging_content, root)
    except OSError as e:
        # ③ 失败：root 缺失、old 在位 → 即刻回滚再上抛
        try:
            os.rename(old_dir, root)
        except OSError as re:
            raise ApplyError(
                "swap",
                f"staging 就位失败（{e}）且回滚失败（{re}）——框架根缺失，"
                f"请人工恢复 {old_dir}",
            ) from re
        raise ApplyError("swap", f"staging 就位失败（已回滚）: {e}") from e
    ctx.record_stage("swap", True, f"staging 已就位为 {root}")

    # ④ 起 daemon（stop 逆序）
    if ctx.start_units_fn is not None:
        start_result = ctx.start_units_fn(daemon_roots, dashboard_hosted)
    else:
        start_result = _default_start_units(daemon_roots, dashboard_hosted)
    if start_result.get("errors"):
        raise ApplyError(
            "start",
            f"起服务失败（换装已就位，服务未恢复）：errors={start_result['errors']}",
        )
    ctx.record_stage("start", True, "全部 unit 已按 stop 逆序拉起")
    return {"old_dir": old_dir, "stop": stop_result}


def rollback_swap(
    ctx: ApplyContext,
    old_dir: Path,
    failed_stage: str,
    error: str,
) -> dict:
    """失败回滚：回滚副本恢复为框架根 → 起 daemon。

    回滚结果记入 ``ctx.rollback_info``，终态由 run_apply_orchestration 的
    统一写点落盘（避免双写点覆盖回滚字段——单写点纪律）。回滚自身失败
    （框架根缺失/半新态）抛 ApplyError，状态收口仍由统一写点完成。
    """
    root = ctx.framework_root
    ts = time.strftime("%Y%m%d-%H%M%S")
    restored = False
    if Path(old_dir).exists():
        if root.exists():
            # 新根已在位（start 阶段失败形态）：先摘除到唯一失败暂存名
            failed_dir = root.parent / f"{root.name}.update-failed-{ts}"
            try:
                os.rename(root, failed_dir)
            except OSError as e:
                raise ApplyError(
                    "rollback",
                    f"回滚前置摘除失败（{e}）——框架根为半新态，"
                    f"回滚副本在 {old_dir}",
                ) from e
        try:
            os.rename(old_dir, root)
            restored = True
        except OSError as e:
            raise ApplyError(
                "rollback",
                f"回滚副本恢复失败（{e}）——框架根缺失，回滚副本在 {old_dir}",
            ) from e
    # 起 daemon（尽力而为；失败原因并入回滚结果）
    daemon_roots = getattr(ctx, "_daemon_roots", None)
    if daemon_roots is None:
        daemon_roots = list(ctx.injected_daemon_roots or [])
    dashboard_hosted = getattr(ctx, "_dashboard_hosted", None)
    if dashboard_hosted is None:
        dashboard_hosted = bool(ctx.injected_dashboard)
    start_errors = []
    try:
        if ctx.start_units_fn is not None:
            result = ctx.start_units_fn(daemon_roots, dashboard_hosted)
        else:
            result = _default_start_units(daemon_roots, dashboard_hosted)
        start_errors = result.get("errors") or []
    except Exception as e:  # noqa: BLE001
        start_errors.append(str(e))
    ctx.rollback_info = {
        "rollback": True,
        "rollback_restored": restored,
        "rollback_start_errors": start_errors,
    }
    return ctx.rollback_info


# ── 2.5 幂等恢复与代际清理 ────────────────────────────────────────────


def recover_interrupted(ctx: ApplyContext) -> str:
    """编排启动时检测残留 staging/``.old-*``，按记录续走或回滚（幂等恢复）。

    Returns: 人读处置摘要（无残留返回 ""）。
    """
    root = ctx.framework_root
    parent = root.parent
    notes = []
    # 残留 .old + 根缺失 = 换装中途断（②完成、③前断）→ 回滚恢复
    olds = sorted(parent.glob(f"{root.name}.old-*"))
    if olds and not root.exists():
        newest = olds[-1]
        try:
            os.rename(newest, root)
            notes.append(f"幂等恢复：回滚副本 {newest.name} 已恢复为框架根")
            for stale in olds[:-1]:
                _rmtree(stale)
        except OSError as e:
            raise ApplyError(
                "recover",
                f"幂等恢复失败：{e}（回滚副本 {newest} 须人工恢复）",
            ) from e
    # 残留 .update-failed-*（回滚前置摘除后进程死）→ 摘除态即弃置，直接清理
    for stale in sorted(parent.glob(f"{root.name}.update-failed-*")):
        _rmtree(stale)
        notes.append(f"幂等恢复：失败暂存目录 {stale.name} 已清理")
    # 残留 staging：完整性可用则本轮直接接管（续走），否则清理重下
    for stale in sorted(parent.glob("fenixd-update-staging-*")):
        content_roots = [p for p in stale.iterdir() if p.is_dir()] if stale.exists() else []
        usable = len(content_roots) == 1
        if usable:
            try:
                assert_integrity(content_roots[0])
            except ApplyError:
                usable = False
        if usable:
            ctx.recovered_staging = content_roots[0]
            notes.append(f"幂等恢复：接管残留 staging {stale.name}（完整性通过）")
        else:
            _rmtree(stale)
            notes.append(f"幂等恢复：残留 staging {stale.name} 不完整，已清理")
    # 成功换装后的代际清理不在此处（成功路径末尾执行）；此处只把「根在位 +
    # 多代 .old」收缩为一代，防止无限代际堆积
    if root.exists():
        olds = sorted(parent.glob(f"{root.name}.old-*"))
        for stale in olds[:-1]:
            _rmtree(stale)
    return "；".join(notes)


def cleanup_old_generations(ctx: ApplyContext, keep: Path) -> str:
    """成功换装后仅保留一代回滚副本（keep=本次换装产生的 .old-<ts>）。"""
    parent = ctx.framework_root.parent
    removed = []
    for stale in sorted(parent.glob(f"{ctx.framework_root.name}.old-*")):
        if Path(stale) == Path(keep):
            continue
        _rmtree(stale)
        removed.append(stale.name)
    return "、".join(removed)


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


# ── 2.6 dsh-plugins 更新编排 ──────────────────────────────────────────


def _profile_fenix_links(profile_dir: Path, old_plugins_root: Path,
                         framework_root: Path) -> dict:
    """解析单 profile 的 fenix 插件 link 依赖，三类分拣。

    Returns: ``{"rebind": [(pkg, dirname)], "framework_internal": [pkg],
    "foreign": 0}``——rebind=link 指向旧插件目录（参与重注册）；
    framework_internal=link 目标位于框架根内（随框架换装一并就位，检出
    不参与独立插件更新，design D6 边界）；foreign=非 fenix 插件（零触碰）。
    """
    pkg_path = profile_dir / "package.json"
    try:
        payload = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {"rebind": [], "framework_internal": [], "foreign": 0}
    deps = payload.get("dependencies") if isinstance(payload, dict) else None
    if not isinstance(deps, dict):
        return {"rebind": [], "framework_internal": [], "foreign": 0}
    old_root = Path(old_plugins_root).resolve()
    fw_root = Path(framework_root).resolve()
    result = {"rebind": [], "framework_internal": [], "foreign": 0}
    for pkg, ref in deps.items():
        if not (isinstance(ref, str) and ref.startswith("link:")):
            continue
        target = ref[len("link:"):]
        if not target:
            continue
        try:
            resolved = Path(target).resolve()
        except (OSError, RuntimeError, ValueError):
            resolved = Path(target)
        if _is_under(resolved, fw_root):
            result["framework_internal"].append(pkg)
        elif _is_under(resolved, old_root):
            result["rebind"].append((pkg, resolved.name))
        else:
            result["foreign"] += 1
    return result


def _is_under(path: Path, ancestor: Path) -> bool:
    """path 是否位于 ancestor 之下（含相等；双方已 resolve）。"""
    try:
        path.relative_to(ancestor)
        return True
    except ValueError:
        return False


def verify_plugin_exports(plugin_dir: Path) -> list:
    """逐插件核验 ``exports`` 指向文件存在；缺失路径清单返回（空=通过）。"""
    pkg_path = Path(plugin_dir) / "package.json"
    try:
        payload = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return ["package.json 不可读"]
    exports = payload.get("exports") if isinstance(payload, dict) else None
    if exports is None:
        return []
    missing = []
    base = Path(plugin_dir)

    def _walk(node):
        if isinstance(node, str):
            if node.startswith("./"):
                node = node[2:]
            if node and not node.startswith("*") and "." in node.split("/")[-1]:
                if not (base / node).exists():
                    missing.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(exports)
    return missing


def update_plugins(ctx: ApplyContext, target_tag: str) -> dict:
    """插件更新分支（2.6）：zip 校验 → 同级新目录 → 逐 profile 重注册 → exports 验证。

    与框架分支相互独立：本函数抛 ApplyError 只标记插件边失败，不阻断框架
    更新结果。无插件安装态（无 profiles/无 dsh-plugins-* link）→ 跳过并注明。
    目标版本恒取远端 latest（stable-only 语义；target_tag 参数仅供读侧语义，
    不覆盖 latest 判定）。
    """
    profiles_dir = ctx.profiles_dir
    if profiles_dir is None:
        from core.dsh_session_tidy import resolve_dsh_home

        profiles_dir = resolve_dsh_home() / "profiles"
    profiles_dir = Path(profiles_dir)
    state = detect_plugins_state(profiles_dir=profiles_dir)
    if not state.get("version"):
        return {"status": "skipped",
                "detail": "未发现 dsh-plugins 插件安装态，跳过插件更新"}

    # 各 profile 的旧**版本根**（dsh-plugins-<tag> 目录）：plugin_root 可能是
    # 插件包目录（父为版本根）或版本根本身，按目录名形态归一
    from core.self_update import plugins_version_from_dirname

    old_version_roots = {}
    for name, info in (state.get("profiles") or {}).items():
        if not info.get("plugin_root"):
            continue
        p = Path(info["plugin_root"])
        if plugins_version_from_dirname(p.name):
            old_version_roots[name] = p
        else:
            old_version_roots[name] = p.parent
    if not old_version_roots:
        return {"status": "skipped", "detail": "profiles 无可解析插件根，跳过"}

    fw_root = Path(ctx.framework_root).resolve()
    parents = {root.parent for root in old_version_roots.values()}
    if len(parents) != 1:
        # 多 profile 指向不同父目录：保守取其一（单 profile 为常态；异常形态
        # 以首个 profile 的父目录为基线，其余 profile 的重注册按各自 old root 判定）
        first = next(iter(old_version_roots.values()))
        old_plugins_root = first.parent
    else:
        old_plugins_root = next(iter(parents))
    if _is_under(Path(old_plugins_root).resolve(), fw_root):
        return {
            "status": "skipped",
            "detail": (
                "插件目录位于框架根内（源码/工作树形态安装），不参与独立插件更新"
                "——随框架换装一并就位"
            ),
        }

    release = fetch_latest_release(PLUGINS_REPO, http_get=ctx.http_get)
    downloads_dir = Path(ctx.update_dir) / "downloads" / f"plugins-{time.strftime('%Y%m%d-%H%M%S')}"
    zip_path = download_and_verify(
        release, f"dsh-plugins-{release.tag_name}.zip", downloads_dir,
        mirror=(ctx.config.mirror if ctx.config else ""), http_get=ctx.http_get,
        download_impl=ctx.download_impl,
    )
    # 解压目标 = 旧插件目录同级（MUST NOT 落在框架根内——design D6 边界）
    new_parent = Path(old_plugins_root).parent
    if _is_under(new_parent.resolve(), fw_root):
        raise ApplyError(
            "plugins",
            "插件新目录解压目标位于框架根内（违反 design D6 边界），插件更新中止",
        )
    new_root = extract_to_staging(
        zip_path, new_parent / f"plugins-staging-{time.strftime('%Y%m%d-%H%M%S')}")
    expected_new_root = new_parent / f"dsh-plugins-{release.tag_name}"
    if new_root != expected_new_root:
        try:
            os.rename(new_root, expected_new_root)
        except OSError as e:
            raise ApplyError("plugins", f"插件新目录就位失败: {e}") from e

    # 逐 profile 重注册
    rebind_detail = []
    desktop_detected = False
    errors = []
    try:
        profile_entries = sorted(p for p in profiles_dir.iterdir() if p.is_dir())
    except OSError:
        profile_entries = []
    for pdir in profile_entries:
        pname = pdir.name
        profile_old_root = old_version_roots.get(pname, old_plugins_root)
        links = _profile_fenix_links(pdir, profile_old_root, ctx.framework_root)
        if pname == "desktop":
            if links["rebind"]:
                desktop_detected = True
            continue  # desktop profile 不自动改写（design D6）
        if links["framework_internal"]:
            rebind_detail.append(
                f"{pname}: {len(links['framework_internal'])} 个插件 link 指向框架根内"
                "（随框架换装，跳过重注册）"
            )
        for pkg, dirname in links["rebind"]:
            new_target = expected_new_root / dirname
            if not new_target.exists():
                errors.append(f"{pname}/{pkg}: 新目录缺插件 {dirname}")
                continue
            rc, out, err = _run_dsh(ctx, ["plugin", "--profile", pname, "remove", pkg])
            if rc != 0 and "not found" not in (out + err).lower():
                errors.append(f"{pname}: remove {pkg} 失败: {(err or out).strip()}")
                continue
            rc, out, err = _run_dsh(
                ctx, ["plugin", "--profile", pname, "add", f"link:{new_target}"])
            if rc != 0:
                errors.append(f"{pname}: add {pkg} 失败: {(err or out).strip()}")
                continue
            missing = verify_plugin_exports(new_target)
            if missing:
                errors.append(f"{pname}/{pkg}: exports 指向缺失 {missing}")
            else:
                rebind_detail.append(f"{pname}/{pkg} → {new_target}")
    if desktop_detected:
        rebind_detail.append(f"desktop profile 检出（降级文档指引）：{DESKTOP_GUIDE}")
    if errors:
        raise ApplyError("plugins", "插件重注册失败：" + "；".join(errors[:5]))
    # 清理旧版本根目录（新目录已就位且重注册完成；新根本体不动）
    for pname, old_root in old_version_roots.items():
        if Path(old_root) == Path(expected_new_root):
            continue
        try:
            _rmtree(Path(old_root))
            rebind_detail.append(f"旧插件版本目录 {Path(old_root).name} 已清理")
        except OSError:
            rebind_detail.append(
                f"旧插件版本目录 {Path(old_root).name} 清理失败（保留，不影响新目录生效）")
    if downloads_dir.exists():
        _rmtree(downloads_dir)
    return {"status": "success", "detail": "；".join(rebind_detail),
            "version": release.tag_name}


def _run_dsh(ctx: ApplyContext, args: list) -> "tuple[int, str, str]":
    """dsh CLI 调用（注入缝供测试；插件注册属进程外 CLI，无 daemon 纠缠）。"""
    if ctx.dsh_runner is not None:
        return ctx.dsh_runner(args)
    try:
        proc = subprocess.run(
            ["dsh", *args], capture_output=True, text=True,
            timeout=DSH_CLI_TIMEOUT_S, check=False,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


# ── 框架更新编排（2.2–2.5 串装）──────────────────────────────────────


def apply_framework(ctx: ApplyContext) -> dict:
    """框架更新编排全链：预检 → 下载校验 → staging → 三段式换装 → 清理。"""
    local = read_framework_version(ctx.framework_root)
    if local.form == FORM_SOURCE:
        raise ApplyError(
            "preflight",
            "框架为源码形态（无 VERSION 文件），不参与制品更新（请 git pull）",
        )
    target = ctx.target
    if not target:
        st = read_status(ctx.resolved_status_path()) or {}
        target = (st.get("framework") or {}).get("remote_version")
    if not target:
        raise ApplyError("preflight", "无目标版本（请先执行检查更新）")
    if not is_newer(target, local.version):
        raise ApplyError("preflight",
                         f"目标版本 {target} 不新于本地 {local.version}，拒绝换装")

    # 在飞 run 预检（2.3）：存在在飞 run 拒绝执行（半自动确认后仍过此门）
    roots = (ctx.project_roots_fn or
             (lambda: registered_project_roots(ctx.framework_root)))()
    inflight = find_inflight_runs(roots)
    if inflight:
        sample = inflight[0]
        raise ApplyError(
            "preflight",
            f"存在在飞 run（{len(inflight)} 条，如 {sample['project'].name}:"
            f"{sample['run'].name}），拒绝换装——请等待在飞 run 完成后重试",
        )

    # 远端 release（target 校验 + 资产 URL）
    from core.self_update import FRAMEWORK_REPO

    release = fetch_latest_release(FRAMEWORK_REPO, http_get=ctx.http_get)
    if release.tag_name != target:
        # 检查后远端又前进了：以更新后的 latest 为准（仍走同一强校验链）
        target = release.tag_name
    asset = f"fenixd-{target}.tar.gz"
    if asset not in release.assets:
        raise ApplyError("download", f"release 缺 tar.gz 资产: {asset}")

    # staging：残留接管（幂等恢复）或新建
    staging_dir = ctx.recovered_staging
    downloads_dir = None
    if staging_dir is None:
        ts = time.strftime("%Y%m%d-%H%M%S")
        staging_base = ctx.framework_root.parent / f"fenixd-update-staging-{ts}"
        downloads_dir = Path(ctx.update_dir) / "downloads" / ts
        archive = download_and_verify(
            release, asset, downloads_dir,
            mirror=(ctx.config.mirror if ctx.config else ""),
            http_get=ctx.http_get, download_impl=ctx.download_impl,
        )
        staging_dir = extract_to_staging(archive, staging_base)
    assert_integrity(staging_dir)
    ctx.record_stage("staging", True, f"staging 完整性断言通过: {staging_dir.name}")

    # 服务化目标枚举（停步前的真实枚举；注入缝供测试三段式不触真实 systemd）
    if ctx.injected_daemon_roots is not None or ctx.injected_dashboard is not None:
        ctx._daemon_roots = list(ctx.injected_daemon_roots or [])
        ctx._dashboard_hosted = bool(ctx.injected_dashboard)
    else:
        ctx._daemon_roots, ctx._dashboard_hosted = collect_hosted_targets(roots)
    # 未服务化场景在 swap_in_place 的 stop 阶段注明

    swap_result = swap_in_place(ctx, staging_dir)
    old_dir = swap_result["old_dir"]

    # 换装成功：VERSION 读回断言（spec：更新后 VERSION 读回为目标 tag）
    vpath = Path(ctx.framework_root) / "VERSION"
    try:
        got = vpath.read_text(encoding="utf-8").strip()
    except OSError:
        got = ""
    if got != target:
        raise ApplyError(
            "verify-after",
            f"换装后 VERSION 读回 {got!r} ≠ 目标 {target!r}（制品错位？）",
        )

    removed = cleanup_old_generations(ctx, old_dir)
    ctx.record_stage("cleanup", True,
                     f"保留一代回滚副本 {old_dir.name}" +
                     (f"，清理旧代 {removed}" if removed else ""))
    # 下载暂存清理（校验与解压均已完成，归档不再有消费方）
    if downloads_dir is not None:
        _rmtree(downloads_dir)
    return {"status": "success", "version": target, "old_dir": str(old_dir),
            "stages": list(ctx.stages)}


def is_newer(remote: str, local: str) -> bool:
    from core.self_update import compare_versions

    return compare_versions(remote, local) > 0


# ── 编排主入口（分离进程 main）────────────────────────────────────────


def run_apply_orchestration(ctx: ApplyContext) -> dict:
    """编排主链（分离进程内执行）：锁 → 幂等恢复 → 框架边 ∥ 插件边 → 终态落盘。

    框架与插件相互独立（design D6）：单边失败不阻断另一边；两侧均失败以
    failed 收口并留存双侧原因。
    """
    lpath = ctx.resolved_apply_lock_path()
    lock = UpdateLock(lpath, APPLY_LOCK_STALE_S)
    if not lock.acquire():
        mark_apply_phase(
            APPLY_PHASE_FAILED,
            {"trigger": ctx.source,
             "error": "apply.lock 被占（他方编排进行中），本次编排退出",
             "finished_at": _utcnow_iso()},
            status_path=ctx.resolved_status_path(),
        )
        return {"status": "failed", "error": "apply.lock 被占"}
    try:
        recovery_note = recover_interrupted(ctx)
        mark_apply_phase(
            APPLY_PHASE_RUNNING,
            {"trigger": ctx.source, "started_at": _utcnow_iso(),
             "recovery": recovery_note, "stages": []},
            status_path=ctx.resolved_status_path(),
        )

        fw_result = None
        fw_error = None
        plugins_result = None
        plugins_error = None
        try:
            fw_result = apply_framework(ctx)
        except ApplyError as e:
            fw_error = f"[{e.stage}] {e}"
            # 换装阶段（stop/swap/start/verify-after）失败必须回滚；
            # preflight/下载/staging 断言阶段本地安装零改动（spec 硬门），
            # 无回滚对象（staging 断言失败仅清理 staging）。
            candidates = sorted(ctx.framework_root.parent.glob(
                ctx.framework_root.name + ".old-*"))
            if e.stage in ("stop", "swap", "start", "verify-after") and candidates:
                rollback_swap(ctx, candidates[-1], e.stage, str(e))
        except Exception as e:  # noqa: BLE001 — 编排面未知异常按 failed 收口
            fw_error = f"[unexpected] {e}"
        if fw_error:
            # 框架边失败：残留 staging 清理（换装失败/断言失败场景；换装中途
            # 失败时内容已 rename 走或仍完整，回滚成功后残留 staging 无消费方）
            for stale in sorted(ctx.framework_root.parent.glob(
                    "fenixd-update-staging-*")):
                _rmtree(stale)
        try:
            plugins_result = update_plugins(ctx, target_tag=_plugins_target(ctx))
        except ApplyError as e:
            plugins_error = f"[{e.stage}] {e}"
        except Exception as e:  # noqa: BLE001
            plugins_error = f"[unexpected] {e}"

        finished = _utcnow_iso()
        stages = list(ctx.stages)
        if fw_error and plugins_error:
            updates = {
                "trigger": ctx.source, "stages": stages,
                "error": f"框架边: {fw_error}；插件边: {plugins_error}",
                "framework_error": fw_error, "plugins_error": plugins_error,
                "failed_stage": _stage_of(fw_error),
                "framework": "failed",
            }
            if ctx.rollback_info:
                updates.update(ctx.rollback_info)
            updates["finished_at"] = finished
            mark_apply_phase(APPLY_PHASE_FAILED, updates,
                             status_path=ctx.resolved_status_path())
            result = {"status": "failed", "framework_error": fw_error,
                      "plugins_error": plugins_error}
        else:
            phase = APPLY_PHASE_SUCCESS if fw_result else APPLY_PHASE_FAILED
            updates = {
                "trigger": ctx.source, "stages": stages,
            }
            if fw_result:
                updates.update({
                    "version": fw_result.get("version"),
                    "old_dir": fw_result.get("old_dir"),
                    "framework": "success",
                })
            else:
                updates.update({"error": fw_error, "framework": "failed",
                                "failed_stage": _stage_of(fw_error)})
            if ctx.rollback_info:
                updates.update(ctx.rollback_info)
            if plugins_result:
                updates["plugins"] = plugins_result
            else:
                updates["plugins_error"] = plugins_error
            updates["finished_at"] = finished
            mark_apply_phase(phase, updates,
                             status_path=ctx.resolved_status_path())
            result = {"status": "success" if fw_result else "failed",
                      "framework": fw_result, "plugins": plugins_result,
                      "framework_error": fw_error, "plugins_error": plugins_error}
        append_audit({
            "kind": "apply", "source": ctx.source, "ts": finished,
            "result": result.get("status"),
            "framework_error": fw_error, "plugins_error": plugins_error,
            "stages": [s.get("stage") for s in stages],
        }, ctx.resolved_audits_path())
        return result
    finally:
        lock.release()


def _plugins_target(ctx: ApplyContext) -> Optional[str]:
    st = read_status(ctx.resolved_status_path()) or {}
    return (st.get("plugins") or {}).get("remote_version")


def _stage_of(error: str) -> str:
    if error.startswith("[") and "]" in error:
        return error[1:error.index("]")]
    return "unknown"


def build_context_from_args(args) -> ApplyContext:
    """CLI 参数 → ApplyContext（分离进程入口装配）。"""
    return ApplyContext(
        framework_root=Path(args.framework_root).resolve(),
        source=args.source,
    )


def main(argv: Optional[list] = None) -> int:
    """分离编排进程入口（``python -m core.self_update_apply``）。"""
    parser = argparse.ArgumentParser(description="fenixd 更新应用编排（分离进程）")
    parser.add_argument("--framework-root", required=True)
    parser.add_argument("--source", default="manual")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ctx = build_context_from_args(args)
    try:
        result = run_apply_orchestration(ctx)
    except Exception as e:  # noqa: BLE001 — 分离进程顶层兜底：状态必须收口
        logger.exception("apply orchestration crashed")
        try:
            mark_apply_phase(
                APPLY_PHASE_FAILED,
                {"trigger": ctx.source, "error": f"编排进程崩溃: {e}",
                 "finished_at": _utcnow_iso()},
                status_path=ctx.resolved_status_path(),
            )
        except Exception:  # noqa: BLE001
            pass
        return 1
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())

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
import socket
import subprocess
import sys
import tarfile
import tempfile
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
    detect_plugins_state,
    download_channel_urls,
    fetch_latest_release,
    is_update_available,
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

# 单次下载尝试的墙钟硬上限（秒）：urlopen 的 300s 是 socket 空闲超时——
# 不断流只慢速滴流的传输永不触发（2026-11-28 客户端实证的挂死形态）。
# 600s 内 13.5MB 制品需平均 ≥22KB/s，低于该速率判死传输切进重试机制。
DOWNLOAD_WALL_DEADLINE_S = 600.0

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
        apply_seg = st.get("apply") or {}
        phase = apply_seg.get("phase")
        if phase in (APPLY_PHASE_QUEUED, APPLY_PHASE_RUNNING):
            # 孤儿豁免（queued/running 双形态，宽限口径 APPLY_LOCK_STALE_S
            # 同源——锁面与状态面同一时刻窗一起解楔）：
            # - queued：编排进程可能在 mark RUNNING 前即死（解释器缺失/导入
            #   失败），phase 永久停留 queued；
            # - running：编排进程可能在收尾 mark 前被硬杀（Windows ≤v0.2.2
            #   编排随 dashboard 停服联动 KILL_ON_JOB_CLOSE＝2026-11-28 客户端
            #   实证：新版已落盘而 status 永久停留 running，无豁免会永久
            #   拒绝重触发、更新通道楔死）。
            orphaned = (
                (phase == APPLY_PHASE_QUEUED and _queued_orphaned(apply_seg))
                or (phase == APPLY_PHASE_RUNNING
                    and apply_running_orphaned(apply_seg))
            )
            if not orphaned:
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
        # cwd=str(root.parent)：编排进程绝不能以框架根为 CWD——Windows 禁止
        # 重命名任何存活进程的 CWD 所在目录，编排自身留在旧根里会让 swap 的
        # 旧根 rename 必败（2026-11-28 dockur/windows 容器实证：stop 成功后
        # swap 150ms 内 failed，编排退出后手动 rename 即成功；Linux 无此限制
        # 故从未暴露）。编排全链路用 --framework-root 绝对路径，cwd 落在
        # 父目录（同盘、不参与 rename）是中性落点。
        # keep_job_after_parent=True：Windows 触发方（CLI 受理即退 / dashboard
        # 重启）句柄表销毁不再联动 KILL_ON_JOB_CLOSE 秒杀编排进程——job 句柄
        # 随编排进程自持（2026-11-28 客户端实证阻断级 bug 修复；linux 侧该
        # 形参按签名对齐忽略，setsid 子进程本就独立于触发方）。
        proc = pal.spawn_detached(cmd, cwd=str(root.parent), keep_job_after_parent=True)
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


def _queued_orphaned(apply_seg: dict) -> bool:
    """queued 形态孤儿判定：queued_at 超龄（APPLY_LOCK_STALE_S 同源宽限）。

    编排进程可能在 mark RUNNING 前即死（解释器缺失/导入失败），phase 永久
    停留 queued 楔死更新通道；宽限口径与 UpdateLock 陈锁清扫一致——锁面与
    状态面在同一时刻窗内一起解楔。queued_at 缺失/不可解析维持「不孤儿」
    （宁拒不误清）。
    """
    from core.timelib import now_utc, parse_ts

    ts = parse_ts(apply_seg.get("queued_at") or "")
    if ts is None:
        return False
    return (now_utc() - ts).total_seconds() > APPLY_LOCK_STALE_S


def apply_running_orphaned(apply_seg: dict) -> bool:
    """running 形态孤儿判定：最后活动时间超龄（APPLY_LOCK_STALE_S 同源宽限）。

    编排进程可能在收尾 mark 前被硬杀（Windows ≤v0.2.2 编排随 dashboard 停服
    联动 KILL_ON_JOB_CLOSE 秒杀＝2026-11-28 客户端实证：新版已落盘而 status
    永久停留 running），与 queued 不同此前的实现无豁免会永久拒绝重触发。
    最后活动时间取 ``started_at`` 与 ``stages[-1].ts`` 的较大者（阶段推进即
    落盘；下载中段无 stage 推进，但下载墙钟上界远小于宽限，不会误判存活
    编排）。全部缺失/不可解析维持「不孤儿」（宁拒不误清）。
    """
    from core.timelib import now_utc, parse_ts

    cands = [apply_seg.get("started_at") or ""]
    stages = apply_seg.get("stages")
    if isinstance(stages, list) and stages and isinstance(stages[-1], dict):
        cands.append(stages[-1].get("ts") or "")
    latest = None
    for raw in cands:
        ts = parse_ts(raw)
        if ts is not None and (latest is None or ts > latest):
            latest = ts
    if latest is None:
        return False
    return (now_utc() - latest).total_seconds() > APPLY_LOCK_STALE_S


# ── 编排上下文与注入缝 ─────────────────────────────────────────────────


@dataclass
class ApplyContext:
    """编排上下文：路径配置 + 测试注入缝（stop/start/registry/dsh 全可注入）。"""

    framework_root: Path
    source: str = "manual"
    update_dir: Path = UPDATE_DIR
    profiles_dir: Optional[Path] = None  # None → resolve_dsh_home()/profiles
    target: Optional[str] = None  # 读侧语义目标 tag（apply 换装恒取远端 latest，stable-only）
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
    # 本轮 swap_in_place 真实 rename 出的回滚副本（②成功后登记；③失败自回滚
    # 成功即消费清空）。编排面回滚对象 MUST 绑定该字段而非按目录名取最新
    # .old-*——cleanup_old_generations 恒保留一代上轮副本，误选会静默降级
    # （code-review d88bbf6b8b80）。
    last_swap_old_dir: Optional[Path] = None

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
            # dsh 取证旁路 dump（<run_id>.dsh-events.jsonl）非 run 产物：事件
            # 词表无终态类型，runs retention 要等 mtime 停更超 30 分钟判 stale
            # 才移入 archive——不过滤会把已完结 dsh run 结束后数十分钟内误判
            # 在飞、apply 预检据此拒绝换装。排除口径与 liveness 模块的
            # _is_dsh_events_dump / run_files.archive_spec_runs / dashboard
            # 读侧同款（code-review 712f442fbeea）
            if run_file.stem.endswith(".dsh-events"):
                continue
            try:
                idle = moment - run_file.stat().st_mtime
            except OSError:
                continue
            if 0 <= idle <= max_idle_s:
                inflight.append({"project": Path(proot), "run": run_file,
                                 "idle_s": round(idle, 1)})
    return inflight


# ── 2.2 下载 / 校验 / staging ─────────────────────────────────────────


class UpdateProgressWriter:
    """下载进度落盘（PROGRESS_PATH；读侧仅 apply 进行中透出，2026-11-28）。

    独立小文件而非并入 status.json：下载循环 chunk 级高频覆写与编排面的
    status.lock 读合并写互不相干；全部写面吞 OSError——进度条缺席只是
    降级，绝不影响下载与校验主链（spec 硬门在此之外的 sha256）。
    """

    _MIN_INTERVAL_S = 0.4  # chunk 级 update 的落盘节流（墙钟，单调时钟）

    def __init__(self, path: Path):
        self._path = Path(path)
        self._asset = ""
        self._attempt = 1
        self._last_emit = 0.0

    def _emit(self, payload: dict) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload["asset"] = payload.get("asset") or self._asset
            payload["updated_at"] = _utcnow_iso()
            if "attempt" not in payload:
                payload["attempt"] = self._attempt
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent), prefix=".progress-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self._path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except OSError:
            pass

    @staticmethod
    def _pct(done: int, total) -> Optional[float]:
        if not total:
            return None
        return round(min(done / total, 1.0) * 100.0, 1)

    def start(self, asset: str, total, attempt: int = 1) -> None:
        self._asset = asset
        self._attempt = attempt
        self._last_emit = time.monotonic()
        self._emit({"stage": "download", "downloaded": 0,
                    "total": total, "percent": self._pct(0, total),
                    "attempt": attempt})

    def update(self, done: int, total, force: bool = False) -> None:
        now = time.monotonic()
        if not force and done != total and now - self._last_emit < self._MIN_INTERVAL_S:
            return  # 终点字节不受节流（校验窗口内 UI 读到的是完成态而非起点）
        self._last_emit = now
        self._emit({"stage": "download", "downloaded": done,
                    "total": total, "percent": self._pct(done, total)})

    def verify(self, asset: str) -> None:
        self._asset = asset
        self._emit({"stage": "verify", "downloaded": None,
                    "total": None, "percent": None})

    def finish(self) -> None:
        """终态清理（编排收口/下一次下载起点）：进度文件缺席 = 无进度条。"""
        try:
            self._path.unlink()
        except OSError:
            pass


def _progress_writer(ctx: "ApplyContext") -> UpdateProgressWriter:
    """编排上下文绑定的进度写面（路径单点：ctx.update_dir/progress.json）。"""
    return UpdateProgressWriter(Path(ctx.update_dir) / "progress.json")


def _download_file(url: str, dest: Path,
                   download_impl: Optional[Callable] = None,
                   progress: Optional[UpdateProgressWriter] = None) -> Path:
    """下载制品到 dest（流式落盘；注入缝供测试假资产）。

    网络面故障（读停滞超时/连接重置/响应截断等）自动重试：GitHub 制品
    CDN（release-assets.githubusercontent.com）在部分网络下长连接易中途
    停滞——单次下载失败率高，换新连接重试通常即可通过。重试穷尽后按
    ApplyError("download") 收口（编排面据 stage 判定零改动与回滚语义，
    裸 socket 异常上穿会被记成 unexpected 阶段，2026-11-28 实证）。

    progress 非 None 时按 attempt 重置起点写下载进度（Content-Length
    缺失 → total/percent 为 null，UI 退化为字节数文本）。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if download_impl is not None:
        download_impl(url, dest)
        return dest
    import http.client
    import time
    import urllib.error
    import urllib.request

    attempts = 3
    retry_delays = (2.0, 5.0)
    last_err: Optional[Exception] = None
    for attempt in range(attempts):
        wall_deadline = time.monotonic() + DOWNLOAD_WALL_DEADLINE_S
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "fenixd-self-update"})
            with urllib.request.urlopen(req, timeout=max(QUERY_TIMEOUT_S, 300)) as resp, \
                    open(dest, "wb") as f:
                # Content-Length 无条件读取（尺寸断言是普适防线，不止 UI 进度）；
                # 测试假响应可无 headers（getattr 防御，total=None 跳过断言）。
                resp_headers = getattr(resp, "headers", None)
                raw_len = resp_headers.get("Content-Length") if resp_headers else None
                try:
                    total = int(raw_len) if raw_len else None
                except (TypeError, ValueError):
                    total = None
                if progress is not None:
                    progress.start(dest.name, total, attempt=attempt + 1)
                done = 0
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress.update(done, total)
                    if time.monotonic() > wall_deadline:
                        # 慢速滴流防线：socket 空闲超时对不断流的慢传输永不
                        # 触发，墙钟硬上限把死传输切进重试机制。
                        raise socket.timeout(
                            f"下载墙钟超限（>{DOWNLOAD_WALL_DEADLINE_S:.0f}s，"
                            f"已收 {done} 字节）"
                        )
                if progress is not None:
                    progress.update(done, total, force=True)  # EOF 终态必写
                if total is not None and done != total:
                    # 尺寸断言前置：连接「干净」提前截断不抛异常（EOF 静默
                    # 短读），不等 sha256 即判截断进重试（12:47 客户端故障
                    # 形态：13.5MB 只到手部分字节，哈希不符才拦截）。
                    raise http.client.IncompleteRead(bytes(done), total)
            return dest
        except (urllib.error.URLError, http.client.HTTPException,
                socket.timeout, OSError) as e:
            # socket.timeout ⊂ OSError（3.10+ 为 TimeoutError 别名），显式列出
            # 仅表意；HTTPException 族（IncompleteRead 等）非 OSError 需单列。
            last_err = e
            try:
                if dest.exists():
                    dest.unlink()
            except OSError:
                pass
            if attempt + 1 < attempts:
                time.sleep(retry_delays[min(attempt, len(retry_delays) - 1)])
    raise ApplyError(
        "download",
        f"制品下载失败（重试 {attempts - 1} 次后仍超时/中断）: {last_err}"
        "——可配置 update.mirror 走镜像后重试",
    )


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
    for cand_name in candidates:
        url = release.assets.get(cand_name)
        if not url:
            continue
        # 双通道候选（镜像优先直连兜底）逐一尝试：单通道网络失败/非 200
        # 换下一通道，通道穷尽才落到下一候选文件。
        for chan_url in download_channel_urls(url, mirror):
            try:
                status, body = getter(chan_url)
            except Exception:  # noqa: BLE001 — 单通道网络失败换下一通道
                continue
            if status != 200 or not body:
                continue
            mapping = _parse_sha256sum(body.decode("utf-8", errors="replace"))
            if asset_name in mapping:
                return mapping[asset_name]
            # 单资产文件形态：文件内容可能是裸 hash 或 hash+文件名
            if len(mapping) == 1:
                return next(iter(mapping.values()))
            lines = body.decode("utf-8", errors="replace").strip().splitlines()
            if not lines:
                # 空白体候选不可用：换下一候选；全部候选均不可得由循环末尾统一
                # 按 ApplyError("verify") 收口（不以上穿 IndexError 形态逃逸）
                continue
            token = lines[0].split()[0].strip().lower()
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
    progress: Optional[UpdateProgressWriter] = None,
) -> Path:
    """下载资产 + sha256 强校验（失败即中止，本地安装零改动，spec 硬门）。

    下载走双通道候选（download_channel_urls：配置镜像在前、官方直连兜底；
    显式官方则仅直连），每通道独立享受 _download_file 的 3 次连接重试——
    任一通道成功即继续；全败收口 ApplyError("download")。
    """
    url = release.assets.get(asset_name)
    if not url:
        raise ApplyError("download", f"release 资产缺失: {asset_name}")
    dest = Path(dest_dir) / asset_name
    channels = download_channel_urls(url, mirror)
    last_err: Optional[Exception] = None
    for chan_url in channels:
        try:
            _download_file(chan_url, dest,
                           download_impl=download_impl, progress=progress)
            break
        except Exception as e:  # noqa: BLE001 — 单通道失败换下一通道
            last_err = e
            try:
                if dest.exists():
                    dest.unlink()
            except OSError:
                pass
    else:
        raise ApplyError(
            "download",
            f"制品下载失败（镜像与官方直连双通道均不可达，末次错误: {last_err}）"
            "——可配置 update.mirror 更换镜像后重试",
        )
    try:
        if progress is not None:
            progress.verify(asset_name)
        expected = _fetch_expected_sha256(
            release, asset_name, mirror=mirror, http_get=http_get,
        )
    except ApplyError:
        raise
    except Exception as e:  # noqa: BLE001 — 网络面裸异常归位 verify 阶段
        raise ApplyError("verify", f"sha256 资产下载失败: {e}") from e
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
    if progress is not None:
        progress.finish()
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
            members = tf.getmembers()
            if not _safe_archive_members(m.name for m in members):
                raise ApplyError("staging", "制品归档含不安全路径（绝对路径/..），拒绝解压")
            # 链接成员拒绝：symlink/hardlink 的 linkname 可指向 staging 外，
            # 先释放外部链接再借后续成员穿链写出是实际生效的对抗面（期望
            # sha256 与制品同走 mirror，镜像被替换时校验链整体失效，此防线
            # 即唯一屏障）；显式 data filter 为第二道（py3.10/3.11 无该参数）
            links = [m.name for m in members if m.issym() or m.islnk()]
            if links:
                raise ApplyError(
                    "staging",
                    f"制品归档含链接成员（{links[:3]}…），拒绝解压"
                    if len(links) > 3 else
                    f"制品归档含链接成员（{links}），拒绝解压",
                )
            try:
                tf.extractall(staging_base, filter="data")
            except TypeError:  # py3.10/3.11 无 filter 参数（链接成员已先行拒绝）
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
    """枚举当前活跃的服务化进程：项目 daemon 根列表 + dashboard 承载在位否。

    Linux systemd 承载经 pal D 组 is_running（unit_active 单源）；dashboard
    双承载判定：systemd unit（systemctl_available + unit_installed +
    unit_active）或 Windows NSSM/sc 服务 ``fenix-dashboard``（用户自建
    NSSM 服务的实证场景，2026-11-28——其工作目录即旧框架根，不纳入停起
    集会让换装 rename 撞句柄锁确定性失败）。全部判定失败降级为「未服务
    化」（跳过停步并在结果注明，spec 口径）。
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
    if not dashboard_hosted:
        # systemd 未命中（典型：Windows）→ NSSM/sc 服务探测兜底。
        try:
            from core.systemd_hosting import (
                windows_service_active,
                windows_service_installed,
            )

            dashboard_hosted = (
                windows_service_installed() and windows_service_active()
            )
        except Exception:  # noqa: BLE001
            dashboard_hosted = False
    return daemon_roots, bool(dashboard_hosted)


def _default_stop_units(daemon_roots, dashboard_hosted) -> dict:
    """停全部服务化进程：项目 daemon 经 pal.stop（双平台单源）+ dashboard 承载。

    dashboard 按平台分派：Windows NSSM/sc 服务（sc stop）或 systemd unit
    （stop_unit_no_block）——pal.IS_WINDOWS 是平台分支唯一合法替身。
    """
    errors = []
    for proot in daemon_roots:
        try:
            pal.stop(proot)
        except Exception as e:  # noqa: BLE001
            errors.append(f"stop {proot.name}: {e}")
    if dashboard_hosted:
        try:
            if pal.IS_WINDOWS:
                from core.systemd_hosting import windows_service_stop

                windows_service_stop()
            else:
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
            if pal.IS_WINDOWS:
                from core.systemd_hosting import windows_service_start

                windows_service_start()
            else:
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
        # stop 失败时旧根尚未 rename（本轮无回滚对象；编排面回滚阶段清单
        # 亦不含 stop，已停 unit 的恢复只靠此处）——先按 stop 逆序尽力重启
        # 再上抛（still_running 形态对仍在运行的 unit 重启为幂等 no-op；
        # 重启失败原因并入失败上抛，不阻断失败收口）
        try:
            if ctx.start_units_fn is not None:
                rescue = ctx.start_units_fn(daemon_roots, dashboard_hosted)
            else:
                rescue = _default_start_units(daemon_roots, dashboard_hosted)
            rescue_errors = rescue.get("errors") or []
        except Exception as e:  # noqa: BLE001 — 尽力而为，不影响失败上抛
            rescue_errors = [str(e)]
        for err in rescue_errors:
            stop_result.setdefault("errors", []).append(f"恢复重启失败: {err}")
        raise ApplyError(
            "stop",
            f"停服务失败（已尽力重启已停 unit）：errors={stop_result.get('errors')} "
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
    ctx.last_swap_old_dir = old_dir
    ctx.record_stage("swap", True, f"旧根已保留为 {old_dir.name}")

    # ③ staging 就位为框架根（路径不变——既有项目骨架链接全部继续有效）
    try:
        os.rename(staging_content, root)
    except OSError as e:
        # ③ 失败：root 缺失、old 在位 → 即刻回滚再上抛
        try:
            os.rename(old_dir, root)
            # 自回滚已消费本轮副本：清空绑定，编排面不再对其触发回滚
            ctx.last_swap_old_dir = None
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
    # 归属校验（code-review d88bbf6b8b80）：传入 old_dir 与本轮换装绑定副本
    # 不一致时拒绝回滚——防「上一代 .old 恢复为框架根」的静默降级与当前版本
    # 被摘除后遭 recover_interrupted 清理。未绑定（本轮无换装）保持宽松语义，
    # 由调用方（编排面）自行把门。
    bound = getattr(ctx, "last_swap_old_dir", None)
    if bound is not None and Path(old_dir) != Path(bound):
        raise ApplyError(
            "rollback",
            f"回滚对象校验失败：{old_dir} 不属本轮换装（本轮绑定 {bound}），"
            "拒绝回滚防代际误降级，请人工核对目录状态",
        )
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
            target_path = Path(target)
            if not target_path.is_absolute():
                # link: 相对形态按 package.json 所在 profile 目录为基准解析
                # （npm/pnpm link: 协议允许相对路径；按编排进程 cwd 解析会把
                # 相对目标误分拣 foreign 零触碰，旧版本根 _rmtree 后 link 断链
                # ——code-review 924e3dc11194）
                target_path = profile_dir / target_path
            resolved = target_path.resolve()
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
    # 远端不新于本地即跳过（与框架边 is_newer 硬门同构）：同版重装会对在用
    # 插件根做删后重建（expected_new_root 已在盘时先 _rmtree 再 rename），
    # 正常触发只是整轮无意义的下载+全量 remove/add 重注册 churn，而 rmtree
    # 与 rename 间隙编排进程被杀会让插件根永久删除、profiles link 悬空且
    # plugins-staging-* 不在 recover_interrupted 接管名单内（无自愈）——
    # code-review 111c76f5474f
    local_version = state.get("version")
    if not is_update_available(local_version, release.tag_name):
        return {"status": "skipped",
                "detail": (f"本地 dsh-plugins {local_version} 已不新于远端 "
                           f"{release.tag_name}，跳过插件更新")}
    downloads_dir = Path(ctx.update_dir) / "downloads" / f"plugins-{time.strftime('%Y%m%d-%H%M%S')}"
    zip_path = download_and_verify(
        release, f"dsh-plugins-{release.tag_name}.zip", downloads_dir,
        mirror=(ctx.config.mirror if ctx.config else ""), http_get=ctx.http_get,
        download_impl=ctx.download_impl, progress=_progress_writer(ctx),
    )
    # 解压目标 = 旧插件目录同级（MUST NOT 落在框架根内——design D6 边界）；
    # old_plugins_root 已是版本根的父目录（含 dsh-plugins-<tag> 子目录）
    new_parent = Path(old_plugins_root)
    if _is_under(new_parent.resolve(), fw_root):
        raise ApplyError(
            "plugins",
            "插件新目录解压目标位于框架根内（违反 design D6 边界），插件更新中止",
        )
    try:
        new_root = extract_to_staging(
            zip_path,
            new_parent / f"plugins-staging-{time.strftime('%Y%m%d-%H%M%S')}")
        expected_new_root = new_parent / f"dsh-plugins-{release.tag_name}"
        if new_root != expected_new_root:
            if expected_new_root.exists():
                # 幂等：上次编排可能已在「就位完成、重注册失败」处中断——同名
                # 同 tag 新目录已残留在盘而 profiles 仍链旧根，直接 rename 会因
                # 目标已存在确定性失败；先清理残根再就位（新内容经 sha256 强校验）
                _rmtree(expected_new_root)
            try:
                os.rename(new_root, expected_new_root)
            except OSError as e:
                raise ApplyError("plugins", f"插件新目录就位失败: {e}") from e
    except Exception:
        # 解压/就位失败：plugins-staging-* 残留先回收再上抛（半截 staging 不在
        # recover_interrupted 接管名单内、无自愈，反复失败线性累积占盘——
        # code-review c3cb1f048bd8；本轮 downloads 暂存由编排失败收口统一回收）
        for stale in sorted(new_parent.glob("plugins-staging-*")):
            _rmtree(stale)
        raise

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
    # 清理旧版本根目录（新目录已就位且重注册完成；新根本体不动；
    # 多 profile 指向同一版本根时去重，清理一次）
    cleaned = set()
    for pname, old_root in old_version_roots.items():
        if Path(old_root) == Path(expected_new_root) or Path(old_root) in cleaned:
            continue
        cleaned.add(Path(old_root))
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
    # 在飞 run 预检（2.3）：存在在飞 run 拒绝执行（半自动确认后仍过此门）；
    # 预检先于任何网络交互（无网也可被在飞 run 快速拒绝）
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

    # 目标版本恒取远端 latest（stable-only 语义：检查后远端前进以更新后的
    # latest 为准；ctx.target/检查状态 remote_version 仅供读侧语义，与插件
    # 边 target_tag 同口径，不参与换装版本判定——原「解析链恒被 latest 覆盖」
    # 的死分支已收口为单一写法，行为不变）
    from core.self_update import FRAMEWORK_REPO

    release = fetch_latest_release(FRAMEWORK_REPO, http_get=ctx.http_get)
    target = release.tag_name
    if not is_newer(target, local.version):
        raise ApplyError("preflight",
                         f"目标版本 {target} 不新于本地 {local.version}，拒绝换装")
    asset = f"fenixd-{target}.tar.gz"
    if asset not in release.assets:
        raise ApplyError("download", f"release 缺 tar.gz 资产: {asset}")

    # staging：残留接管（幂等恢复）或新建
    staging_dir = ctx.recovered_staging
    downloads_dir = None
    if staging_dir is not None:
        # 接管前核对残留 staging 的 VERSION 与本轮 target 一致：可能是上一轮
        # （当时 latest 较旧）的残留，错版换装要到 verify-after 才被拦截并
        # 触发整轮回滚（白走一次停起服务）——不一致按「不完整」清理重下
        try:
            staged = (staging_dir / "VERSION").read_text(
                encoding="utf-8").strip()
        except OSError:
            staged = ""
        if staged != target:
            _rmtree(staging_dir.parent)
            ctx.recovered_staging = None
            staging_dir = None
    if staging_dir is None:
        ts = time.strftime("%Y%m%d-%H%M%S")
        staging_base = ctx.framework_root.parent / f"fenixd-update-staging-{ts}"
        downloads_dir = Path(ctx.update_dir) / "downloads" / ts
        archive = download_and_verify(
            release, asset, downloads_dir,
            mirror=(ctx.config.mirror if ctx.config else ""),
            http_get=ctx.http_get, download_impl=ctx.download_impl,
            progress=_progress_writer(ctx),
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
        # 配置单次解析（分离进程 CLI 装配不注入 config → 此处读用户级配置）：
        # mirror 缺省通道（键缺失 → UPDATE_MIRROR_DEFAULT）由此落到 ctx.config，
        # 下载面双通道候选由其驱动——缺省镜像不能依赖调用方装配。
        if ctx.config is None:
            ctx.config = load_update_config()
        recovery_note = recover_interrupted(ctx)
        _progress_writer(ctx).finish()  # 崩溃残留的上一轮进度文件不跨轮存活
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
            # 换装阶段（swap/start/verify-after）失败必须回滚，且回滚对象
            # MUST 绑定本轮 swap_in_place 真实 rename 出的副本（ctx.last_swap_
            # old_dir）：cleanup_old_generations 恒保留一代上轮 .old 副本，按
            # 目录名取「最新 .old-*」会把上一代旧版本当回滚对象——当前版本根
            # 被摘成 .update-failed-*、上一代旧版恢复为框架根（静默降级），
            # 随后 recover_interrupted 无条件清理 .update-failed-* 将当前版本
            # 永久删除（code-review d88bbf6b8b80）。stop 失败时旧根尚未
            # rename、不存在本轮回滚对象（已停 unit 的恢复由 swap_in_place
            # 内部 rescue 重启承载），不在回滚阶段清单；preflight/下载/staging
            # 断言阶段本地安装零改动（spec 硬门），无回滚对象（staging 断言
            # 失败仅清理 staging）。
            round_old_dir = ctx.last_swap_old_dir
            if e.stage in ("swap", "start", "verify-after") and round_old_dir:
                try:
                    rollback_swap(ctx, round_old_dir, e.stage, str(e))
                except ApplyError as rb_err:
                    # 回滚自身失败并入统一写点（docstring 承诺「状态收口仍由
                    # 统一写点完成」——异常上穿 except 块会跳过 mark_apply_
                    # phase/append_audit，ctx.rollback_info 一并丢失）
                    fw_error = f"{fw_error}；回滚失败: [{rb_err.stage}] {rb_err}"
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
        if fw_error or plugins_error:
            # 失败收口：update/downloads 下载暂存一并回收（本轮 + 崩溃残留轮）
            # ——两侧失败路径原本只清 staging，半截归档/校验失败空目录按失败
            # 次数线性累积占盘且无天龄兜底；apply.lock 串行化编排，盘面上
            # 不存在并发消费方（code-review c3cb1f048bd8）
            downloads_root = Path(ctx.update_dir) / "downloads"
            if downloads_root.is_dir():
                for stale in sorted(downloads_root.iterdir()):
                    _rmtree(stale)

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
            _progress_writer(ctx).finish()
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
            _progress_writer(ctx).finish()
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

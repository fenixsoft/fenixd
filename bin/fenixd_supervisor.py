#!/usr/bin/env python3
"""
fenixd_supervisor.py — fenixd 外部看门狗（fix-admin-self-heal / fix-supervisor-hosting-chain）。

自杀式重启的根因：admin agent 是 daemon 的子进程，直接 kill daemon 会连带杀死
自己，导致「杀完重启」永远走不到、升级也发不出去。本 supervisor 独立于 daemon
运行，承担唯一的重启职责：

- daemon 意外退出（崩溃 / 被杀 / 被请求重启）后自动拉起
- 检测 .fenix/restart_request 文件 → SIGTERM daemon → 等退出 → 重启并清除请求
- .fenix/stop 文件存在时不再拉起（显式停止）
- 每次启动把时间戳写入 .fenix/daemon_started（供 admin/monitor 验证重启生效）

启动方式（推荐）：python3 .fenix/bin/fenixd_supervisor.py --project-root <root>
备选方式：cd <项目根> && python3 .fenix/bin/fenixd_supervisor.py
"""

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


def _resolve_project_root() -> tuple:
    """解析目标项目根，返回 (Path, source 描述)。

    按 --project-root 参数 > FENIX_PROJECT_ROOT 环境变量 > Path.cwd() 解析；
    fix-supervisor-hosting-chain D1：移除 Path(__file__).resolve() 派生路径
    （该路径会跟随项目内 .fenix/bin 软链回到框架主树，导致子项目的 supervisor
    绑定错误目标）。解析结果以绝对路径规范化（expanduser().resolve()）。
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-root", dest="project_root", default=None)
    args, _ = parser.parse_known_args()
    if args.project_root:
        return Path(args.project_root).expanduser().resolve(), "参数 --project-root"
    env_root = os.environ.get("FENIX_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve(), "环境变量 FENIX_PROJECT_ROOT"
    return Path.cwd(), "当前工作目录（cwd）"


PROJECT_ROOT, PROJECT_ROOT_SOURCE = _resolve_project_root()
FENIX_DIR = PROJECT_ROOT / ".fenix"
RESTART_REQUEST = FENIX_DIR / "restart_request"
STOP_FLAG = FENIX_DIR / "stop"
DAEMON_STARTED = FENIX_DIR / "daemon_started"
LOG_FILE = FENIX_DIR / "logs" / "supervisor.log"

# SIGKILL 等待缺省（旧硬编码 60s，interrupt-recovery-preserve D2 起为可配）：
# 排水模式下必须 ≥ daemon 排水窗口 + 固定余量，否则排水期被 SIGKILL 截断。
DEFAULT_SIGKILL_WAIT_SECONDS = 60
# 相对 admin.shutdown_drain_seconds 的固定余量（与 fenixd.py 的
# SUPERVISOR_KILL_MARGIN_SECONDS 同值，保证 daemon 排水期不被 supervisor 截断）。
DRAIN_MARGIN_SECONDS = 120


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_shutdown_drain_seconds() -> int:
    """读取项目级 .fenix/config.yaml 的 admin.shutdown_drain_seconds（D2）。

    解析失败（文件缺失/非 YAML/字段缺失/非法值）回退 0 —— 调用方按
    ``0 = 现行快速停机`` 语义回退 DEFAULT_SIGKILL_WAIT_SECONDS，保持向后兼容。
    """
    import yaml

    cfg_path = FENIX_DIR / "config.yaml"
    try:
        if not cfg_path.exists():
            return 0
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return 0
        admin = data.get("admin")
        if not isinstance(admin, dict):
            return 0
        raw = admin.get("shutdown_drain_seconds")
        if raw is None:
            return 0
        value = int(raw)
        return value if value >= 0 else 0
    except Exception:
        return 0


def _sigkill_wait_seconds() -> int:
    """SIGKILL 等待窗口 = admin.shutdown_drain_seconds + 120s 余量；0 时回退 60s。

    interrupt-recovery-preserve D2：禁止只改 daemon 不改 supervisor——排水窗口
    启用后 supervisor 的 SIGKILL 等待必须不小于 daemon 排水上限，否则排水形同
    虚设。配置缺失/解析失败时回退旧硬编码 60s，行为与旧版逐字节一致。
    """
    drain = _load_shutdown_drain_seconds()
    if drain <= 0:
        return DEFAULT_SIGKILL_WAIT_SECONDS
    return drain + DRAIN_MARGIN_SECONDS


def log(msg: str):
    line = f"{_now_iso()} supervisor: {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ── 启动自报：SIGKILL 等待窗口与启动时间戳（fix-daemon-lifecycle-races D2）──────
# supervisor 每次启动时原子覆写 supervisor_runtime.json，供 daemon 启动
# 自检读取：文件缺失 = 旧代码 supervisor 进程未升级（排水窗口可能被截断）；
# sigkill_wait < drain+120 = 配置漂移（建议重启 supervisor）。
# 路径在调用时经 FENIX_DIR 解析（而非模块加载时固化），保证测试注入
# FENIX_DIR 后写入目标随动。


def _supervisor_runtime_file() -> Path:
    return FENIX_DIR / "supervisor_runtime.json"


def _script_hash() -> str:
    """supervisor 脚本内容 sha256（读取失败返回空串，调用方省略该键）。"""
    try:
        import hashlib
        return hashlib.sha256(
            Path(__file__).absolute().read_bytes()
        ).hexdigest()
    except OSError:
        return ""


def _write_supervisor_runtime() -> None:
    """原子写入 .fenix/supervisor_runtime.json（temp + rename）。

    fix-supervisor-hosting-chain D1/1.3：除既有 sigkill_wait / started_at 外
    追加 pid（自身进程 pid）、script_hash（本脚本内容 sha256，读取失败省略该键
    不中断）、project_root（解析出的绝对项目根）。
    """
    data = {
        "sigkill_wait": _sigkill_wait_seconds(),
        "started_at": _now_iso(),
        "pid": os.getpid(),
        "project_root": str(PROJECT_ROOT),
    }
    script_hash = _script_hash()
    if script_hash:
        data["script_hash"] = script_hash
    import json
    FENIX_DIR.mkdir(parents=True, exist_ok=True)
    target = _supervisor_runtime_file()
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".supervisor_runtime.", suffix=".tmp", dir=str(FENIX_DIR),
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(target))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        log(
            f"supervisor_runtime written: sigkill_wait={data['sigkill_wait']}s, "
            f"started_at={data['started_at']}, pid={data['pid']}"
        )
    except OSError as e:
        log(f"supervisor_runtime write failed (non-blocking): {e}")


def start_daemon():
    """启动 daemon 子进程（经 .fenix/fenixd.py 软链，保持其 FENIX_DIR 解析正确）。"""
    DAEMON_STARTED.write_text(_now_iso() + "\n", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, ".fenix/fenixd.py"],
        cwd=str(PROJECT_ROOT),
        env=os.environ.copy(),
    )


def main():
    # 启动守卫（fix-supervisor-hosting-chain D1）：解析出的项目根下必须存在
    # .fenix/（目录或软链），缺失时打印含解析来源与解析结果的可读错误并以
    # 非零码退出；必须在 _write_supervisor_runtime() 与 start_daemon() 之前返回，
    # 不产生任何进程、不写入任何 runtime 文件。
    if not FENIX_DIR.exists():
        print(
            f"FATAL: supervisor 目标项目根下不存在 .fenix/（{FENIX_DIR}）。\n"
            f"  解析来源: {PROJECT_ROOT_SOURCE}\n"
            f"  解析结果: {PROJECT_ROOT}\n"
            f"  请确认目标是一个已初始化（/fenix-setup 完成）的 Fenixd 项目，"
            f"并显式指定 --project-root 或在项目根下执行本命令。",
            file=sys.stderr,
        )
        sys.exit(2)
    FENIX_DIR.mkdir(parents=True, exist_ok=True)
    log(f"supervisor starting (pid {os.getpid()}, root {PROJECT_ROOT})")
    # 启动自报：SIGKILL 等待窗口 + 启动时间（fix-daemon-lifecycle-races D2）。
    # daemon 启动一致性自检将读取该文件，缺失/不一致 → WARNING 提示重启 supervisor。
    _write_supervisor_runtime()

    while True:
        if STOP_FLAG.exists():
            log("stop flag present — supervisor exiting")
            break

        proc = start_daemon()
        log(f"daemon started (pid {proc.pid})")

        # 监视循环：daemon 存活期间检测重启请求
        restart = False
        while proc.poll() is None:
            if RESTART_REQUEST.exists():
                log("restart_request detected — SIGTERM daemon for restart")
                restart = True
                sigkill_wait = _sigkill_wait_seconds()
                try:
                    proc.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=sigkill_wait)
                except subprocess.TimeoutExpired:
                    log(
                        f"daemon did not exit within {sigkill_wait}s after "
                        f"SIGTERM — SIGKILL"
                    )
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    proc.wait(timeout=5)
                break
            time.sleep(2)

        rc = proc.poll()
        if rc is None:
            # 监视循环内已处理退出，兜底再等
            rc = proc.wait()
        log(f"daemon exited (rc={rc}, restart={'yes' if restart else 'auto'})")

        # 清除重启请求（无论是否因重启请求退出）
        try:
            RESTART_REQUEST.unlink()
        except OSError:
            pass

        if STOP_FLAG.exists():
            log("stop flag present — supervisor exiting")
            break

        # 退避后自动拉起（自愈）
        time.sleep(3)
        log("restarting daemon...")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
fenixd_supervisor.py — fenixd 外部看门狗（fix-admin-self-heal）。

自杀式重启的根因：admin agent 是 daemon 的子进程，直接 kill daemon 会连带杀死
自己，导致「杀完重启」永远走不到、升级也发不出去。本 supervisor 独立于 daemon
运行，承担唯一的重启职责：

- daemon 意外退出（崩溃 / 被杀 / 被请求重启）后自动拉起
- 检测 .fenix/restart_request 文件 → SIGTERM daemon → 等退出 → 重启并清除请求
- .fenix/stop 文件存在时不再拉起（显式停止）
- 每次启动把时间戳写入 .fenix/daemon_started（供 admin/monitor 验证重启生效）

启动方式（cwd 为项目根）：python3 .fenix/bin/fenixd_supervisor.py
"""

import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
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


def start_daemon():
    """启动 daemon 子进程（经 .fenix/fenixd.py 软链，保持其 FENIX_DIR 解析正确）。"""
    DAEMON_STARTED.write_text(_now_iso() + "\n", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, ".fenix/fenixd.py"],
        cwd=str(PROJECT_ROOT),
        env=os.environ.copy(),
    )


def main():
    FENIX_DIR.mkdir(parents=True, exist_ok=True)
    log(f"supervisor starting (pid {os.getpid()}, root {PROJECT_ROOT})")

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

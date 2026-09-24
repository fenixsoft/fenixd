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
import json
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
    return Path.cwd().expanduser().resolve(), "当前工作目录（cwd）"


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

# ── 启动失败熔断（add-stale-code-selfheal D4）──────────────────────────
# 自动重启（陈旧自愈）会把新代码引入运行中的系统——若新代码无法启动则形成
# 「拉起→秒退→拉起」循环。daemon 启动后窗口内退出计为一次启动失败，连续失败
# 达阈值停止自动拉起：写熔断标记（.fenix/supervisor_fused）+ critical 告警，
# 人工修复代码后清除标记（或重启 supervisor 进程）恢复。阈值语义与停止路径的
# SIGKILL/排水常数相反（那些约束「停止」的宽限，这里判定「启动是否成功」），
# 刻意不共用同一常数。
SUPERVISOR_STARTUP_FAIL_WINDOW_SECONDS = 60
SUPERVISOR_STARTUP_FAIL_THRESHOLD = 3


def _fuse_marker() -> Path:
    """熔断标记路径（调用时经 FENIX_DIR 解析，供测试注入 FENIX_DIR 后随动）。"""
    return FENIX_DIR / "supervisor_fused"


def _compute_startup_outcome(alive_seconds: float, fail_count: int) -> int:
    """纯函数：存活 < 窗口计一次启动失败；≥ 窗口重置计数为 0。

    供熔断判定与单测隔离：alive ≥ SUPERVISOR_STARTUP_FAIL_WINDOW_SECONDS 时
    返回 0（本次启动成功，连续失败计数清零）。
    """
    if alive_seconds < SUPERVISOR_STARTUP_FAIL_WINDOW_SECONDS:
        return fail_count + 1
    return 0


def _fuse_blocked() -> bool:
    """熔断标记判定：标记存在且 pid 等于当前 supervisor 进程 → 熔断生效。

    新 supervisor 进程（pid 不同）不继承旧熔断——「重启 supervisor 进程」即
    天然清除熔断状态（与「人工删除标记文件」均为恢复路径）；旧标记按无效处理
    （顺带清理，避免误读残留）。
    """
    marker = _fuse_marker()
    try:
        if not marker.is_file():
            return False
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if isinstance(data, dict) and data.get("pid") == os.getpid():
        return True
    # 标记来自其它 supervisor 进程（或格式损坏）→ 无效，清理后不熔断
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        pass
    return False


def _write_fuse_marker(fail_count: int) -> None:
    """原子写入熔断标记（.fenix/supervisor_fused，含时间戳/失败次数/pid）。"""
    data = {"pid": os.getpid(), "failures": fail_count, "created": _now_iso()}
    target = _fuse_marker()
    try:
        FENIX_DIR.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".supervisor_fused.",
            suffix=".tmp",
            dir=str(FENIX_DIR),
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
        log(f"fuse marker written: {target} (failures={fail_count})")
    except OSError as e:
        log(f"fuse marker write failed (non-blocking): {e}")


def _write_fuse_alert() -> None:
    """熔断触发时经既有告警通道（AdminStore）产出 critical 告警。

    supervisor 是独立进程，写告警需把框架根加入 sys.path 并实例化 AdminStore；
    import/写入失败降级为日志（熔断标记与 supervisor.log critical 记录已落盘，
    告警是增强通道）。测试可用替身注入替换。
    """
    try:
        if str(FENIX_DIR) not in sys.path:
            sys.path.insert(0, str(FENIX_DIR))
        from core.admin_store import AdminStore, ESCALATION

        store = AdminStore(PROJECT_ROOT)
        store.append(
            {
                "kind": ESCALATION,
                "signal_type": "supervisor_fused",
                "spec": None,
                "severity": "critical",
                "description": "daemon 连续启动失败，已停止自动拉起"
                "（熔断标记 .fenix/supervisor_fused）",
                "evidence": (
                    f"连续 {SUPERVISOR_STARTUP_FAIL_THRESHOLD} 次启动后 "
                    f"{SUPERVISOR_STARTUP_FAIL_WINDOW_SECONDS}s 内退出"
                ),
                "action_taken": "supervisor 熔断：停止自动拉起，升级人工",
                "recommended_action": (
                    "修复 daemon 启动失败根因（多为陈旧自愈刚引入的新代码）→ 删除 "
                    ".fenix/supervisor_fused 熔断标记 → 重启 supervisor（或直接重启 "
                    "supervisor 进程，其不继承旧熔断）"
                ),
            }
        )
    except Exception as e:  # noqa: BLE001 — 告警通道非关键路径，失败降级日志
        log(f"fuse alert write failed (non-blocking): {e}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_shutdown_drain_seconds() -> int:
    """读取项目级 .fenix/config.yaml 的 admin.shutdown_drain_seconds（D2）。

    解析失败（文件缺失/非 YAML/字段缺失/非法值）回退 0 —— 调用方按
    ``0 = 现行快速停机`` 语义回退 DEFAULT_SIGKILL_WAIT_SECONDS，保持向后兼容。
    """
    cfg_path = FENIX_DIR / "config.yaml"
    try:
        import yaml

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
    except ImportError:
        # PyYAML 缺失时按契约回退 0（= 现行快速停机），仅告警不中断看门狗
        log("PyYAML 未安装，无法解析 admin.shutdown_drain_seconds，回退 0 (non-blocking)")
        return 0
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


# stdout→LOG_FILE 重定向探测结果缓存：(LOG_FILE 路径, 结论)。该前提（启动命令
# 把 stdout 重定向到 supervisor.log）在进程生命周期内不变，log() 高频路径按
# LOG_FILE 路径惰性缓存探测结果、只探测一次，免去每行日志的 fstat/stat 开销；
# 键含路径，测试 monkeypatch LOG_FILE 后缓存随路径变化自然失效（code-review
# 35745315e198）。
_stdout_redirect_cache = None


def _probe_stdout_points_to_log_file() -> bool:
    """stdout 是否已被重定向到 LOG_FILE（同一文件）。

    实际启动命令把 stdout 与 stderr 都重定向到同一文件
    （`python3 .fenix/bin/fenixd_supervisor.py ... >> .fenix/logs/supervisor.log
    2>&1`），此时若 log() 仍 print 会与文件写形成每行双写。用
    (st_dev, st_ino) 比较 stdout 与 LOG_FILE 是否同一文件；LOG_FILE 尚不存在
    （首次启动尚未 mkdir）时按 inode 无法比较，回退 /proc/self/fd/1 路径解析。
    """
    try:
        out_stat = os.fstat(sys.stdout.fileno())
        try:
            log_stat = LOG_FILE.stat()
        except OSError:
            # LOG_FILE 尚不存在：/proc 路径解析兜底（realpath 规范化比较）
            try:
                fd_link = os.readlink("/proc/self/fd/1")
            except OSError:
                return False
            return os.path.realpath(fd_link) == str(LOG_FILE)
        return (out_stat.st_dev, out_stat.st_ino) == (log_stat.st_dev, log_stat.st_ino)
    except (OSError, ValueError, AttributeError):
        return False


def _stdout_points_to_log_file() -> bool:
    """stdout 是否已被重定向到 LOG_FILE（探测结果按 LOG_FILE 路径惰性缓存）。"""
    global _stdout_redirect_cache
    cache_key = str(LOG_FILE)
    cached = _stdout_redirect_cache
    if cached is not None and cached[0] == cache_key:
        return cached[1]
    result = _probe_stdout_points_to_log_file()
    _stdout_redirect_cache = (cache_key, result)
    return result


def log(msg: str):
    line = f"{_now_iso()} supervisor: {msg}"
    # fix-observability-gaps 4.2：文件写为唯一 sink（stdout 已被重定向到同一
    # LOG_FILE 时不再 print——否则每行双写）。控制台可见性仅当 stdout 未被
    # 重定向到 LOG_FILE 时保留（直接终端运行仍可看到实时日志）。
    if not _stdout_points_to_log_file():
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

        return hashlib.sha256(Path(__file__).absolute().read_bytes()).hexdigest()
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
    FENIX_DIR.mkdir(parents=True, exist_ok=True)
    target = _supervisor_runtime_file()
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=".supervisor_runtime.",
            suffix=".tmp",
            dir=str(FENIX_DIR),
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
    """启动 daemon 子进程（经 .fenix/fenixd.py 软链，保持其 FENIX_DIR 解析正确）。

    写 daemon_started 标记与 Popen 均包 OSError 保护：.fenix 只读/磁盘满等
    异常不再炸穿 main 循环致看门狗无痕退出（daemon 此后永无人拉起）。标记
    写失败仅记日志继续拉起；Popen 失败则删除刚写的伪时间戳（避免 admin/monitor
    误判重启已生效）并返回 None，由调用方按启动失败计数。
    """
    try:
        DAEMON_STARTED.write_text(_now_iso() + "\n", encoding="utf-8")
    except OSError as e:
        log(f"daemon_started marker write failed (non-blocking): {e}")
    try:
        return subprocess.Popen(
            [sys.executable, ".fenix/fenixd.py"],
            cwd=str(PROJECT_ROOT),
            env=os.environ.copy(),
        )
    except OSError as e:
        log(f"daemon spawn failed: {e}")
        try:
            if DAEMON_STARTED.exists():
                DAEMON_STARTED.unlink()
        except OSError:
            pass
        return None


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

    # 连续启动失败计数（add-stale-code-selfheal D4）：仅「意外退出」累计，
    # 优雅重启（restart_request）/ 显式停止不计；存活 ≥ 60s 清零。
    fail_count = 0

    while True:
        if STOP_FLAG.exists():
            log("stop flag present — supervisor exiting")
            break

        # 熔断判定：存在属于当前 supervisor 进程的熔断标记 → 不再拉起。
        # 恢复路径：修复代码后删除标记，或重启 supervisor 进程（不继承旧熔断）。
        if _fuse_blocked():
            log(
                "fuse marker present (pid-matched) — supervisor stops starting daemon. "
                "Fix the startup failure, delete .fenix/supervisor_fused, and restart "
                "supervisor."
            )
            break

        proc = start_daemon()
        if proc is None:
            # Popen 失败（daemon 未启动）：按一次启动失败计入既有熔断计数
            # （存活 0s < 窗口 → +1），达阈值走与意外退出相同的熔断路径；
            # 未达阈值退避后重试，防止无间隔热循环。
            fail_count = _compute_startup_outcome(0.0, fail_count)
            if fail_count >= SUPERVISOR_STARTUP_FAIL_THRESHOLD:
                log(
                    f"CRITICAL: daemon 连续 {fail_count} 次 Popen 失败——"
                    f"停止自动拉起。修复启动失败根因后删除 .fenix/supervisor_fused "
                    f"或重启 supervisor 恢复。"
                )
                _write_fuse_marker(fail_count)
                _write_fuse_alert()
                break
            time.sleep(3)
            log("restarting daemon...")
            continue
        started_ts = time.time()
        log(f"daemon started (pid {proc.pid})")

        # 监视循环：daemon 存活期间检测停止/重启请求
        restart = False
        while proc.poll() is None:
            if STOP_FLAG.exists():
                # 停止协作（fix-supervisor-hosting-chain 验证修复 BUG-01）：
                # stop_daemon 写 stop 后 SIGTERM 可能因竞态落在旧 daemon pid 上
                # （supervisor 正处 3s 退避、尚未拉起新 daemon），或 daemon 被外部
                # 重启换了 pid。监视循环内见 stop 即主动 SIGTERM 当前 daemon 并
                # 退出监视——收口不再依赖「daemon 自己先死」这一前提。
                log("stop flag detected during watch — SIGTERM daemon for stop")
                restart = False
                sigkill_wait = _sigkill_wait_seconds()
                try:
                    proc.send_signal(signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=sigkill_wait)
                except subprocess.TimeoutExpired:
                    log(f"daemon did not exit within {sigkill_wait}s after " f"SIGTERM — SIGKILL")
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        # SIGKILL 后仍可能因不可中断睡眠（D 状态）收尸超时，
                        # 捕获以免异常炸穿 supervisor 主循环；进程最终退出时
                        # 由监视循环外的 proc.wait() 收尸。
                        log(
                            "daemon still alive 5s after SIGKILL "
                            "(uninterruptible sleep?) — leave reaping to outer wait"
                        )
                break
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
                    log(f"daemon did not exit within {sigkill_wait}s after " f"SIGTERM — SIGKILL")
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        # SIGKILL 后仍可能因不可中断睡眠（D 状态）收尸超时，
                        # 捕获以免异常炸穿 supervisor 主循环；进程最终退出时
                        # 由监视循环外的 proc.wait() 收尸。
                        log(
                            "daemon still alive 5s after SIGKILL "
                            "(uninterruptible sleep?) — leave reaping to outer wait"
                        )
                break
            time.sleep(2)

        rc = proc.poll()
        if rc is None:
            # 监视循环内已处理退出，兜底再等
            rc = proc.wait()
        alive_seconds = time.time() - started_ts
        log(
            f"daemon exited (rc={rc}, restart={'yes' if restart else 'auto'}, "
            f"alive={alive_seconds:.0f}s)"
        )

        # 清除重启请求（无论是否因重启请求退出）
        try:
            RESTART_REQUEST.unlink()
        except OSError:
            pass

        if STOP_FLAG.exists():
            log("stop flag present — supervisor exiting")
            break

        # 启动失败熔断：仅意外退出（非优雅重启）计入；存活 < 60s 累加，≥ 60s 清零。
        if not restart:
            fail_count = _compute_startup_outcome(alive_seconds, fail_count)
            if fail_count >= SUPERVISOR_STARTUP_FAIL_THRESHOLD:
                log(
                    f"CRITICAL: daemon 连续 {fail_count} 次启动后 "
                    f"{SUPERVISOR_STARTUP_FAIL_WINDOW_SECONDS}s 内退出——"
                    f"停止自动拉起。修复启动失败根因后删除 .fenix/supervisor_fused "
                    f"或重启 supervisor 恢复。"
                )
                _write_fuse_marker(fail_count)
                _write_fuse_alert()
                break
        else:
            # 优雅重启（supervisor 主动 SIGTERM）不计启动失败、清零连续计数
            fail_count = 0

        # 退避后自动拉起（自愈）
        time.sleep(3)
        log("restarting daemon...")


if __name__ == "__main__":
    main()

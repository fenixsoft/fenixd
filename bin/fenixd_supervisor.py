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
import fcntl
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
    （顺带清理，避免误读残留）；标记损坏/不可读同按未熔断处理（记日志并清理）。
    """
    marker = _fuse_marker()
    try:
        if not marker.is_file():
            return False
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        # 标记损坏/不可读（外部改坏、磁盘问题）：按未熔断 fail-open 处理，但须
        # 留观测痕迹并清理残留（与下方 pid 不匹配路径对称）——否则「拉起→秒退→
        # 拉起」循环无痕恢复且 supervisor.log 零线索（code-review c13d4e9720ad）。
        log(f"fuse marker corrupt/unreadable — treated as not fused (non-blocking): {e}")
        try:
            marker.unlink(missing_ok=True)
        except OSError:
            pass
        return False
    if isinstance(data, dict) and data.get("pid") == os.getpid():
        return True
    # 标记来自其它 supervisor 进程（或格式损坏）→ 无效，清理后不熔断
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        pass
    return False


def _atomic_write_text(target: Path, text: str, tmp_prefix: str, label: str) -> bool:
    """原子写入文本文件的共用实现（mkstemp → fsync → os.replace，失败清理 tmp）。

    mkdir 也在保护内（.fenix 只读/权限异常等）：任一步 OSError → 清理 tmp、
    经 log 记 ``{label} write failed (non-blocking)`` 并返回 False，不炸穿
    调用方；成功返回 True（成功日志文案各异，由各调用方自带）。
    """
    try:
        FENIX_DIR.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=tmp_prefix,
            suffix=".tmp",
            dir=str(FENIX_DIR),
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, str(target))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return True
    except OSError as e:
        log(f"{label} write failed (non-blocking): {e}")
        return False


def _atomic_write_json(target: Path, data: dict, tmp_prefix: str, label: str) -> bool:
    """原子写入 JSON 文件：序列化后走 _atomic_write_text 同一原子写实现。

    code-review 67015590c6ce：_write_fuse_marker / _write_supervisor_runtime /
    _write_daemon_runtime 三处近乎逐行相同的原子写样板收敛为单一实现，消除
    「同型逻辑多处内联、只改一处不改其余」的漂移面（本脚本漂移前科见
    _terminate_daemon docstring 引用的 interrupt-recovery-preserve D2）；
    code-review 3f99b6283270：daemon_started 时间戳标记亦统一到该口径，
    免除 write_text 直接截断写的半写/零写窗口被 admin/monitor 误读。
    """
    return _atomic_write_text(
        target, json.dumps(data, ensure_ascii=False), tmp_prefix, label
    )


def _write_fuse_marker(fail_count: int) -> None:
    """原子写入熔断标记（.fenix/supervisor_fused，含时间戳/失败次数/pid）。"""
    data = {"pid": os.getpid(), "failures": fail_count, "created": _now_iso()}
    if _atomic_write_json(_fuse_marker(), data, ".supervisor_fused.", "fuse marker"):
        log(f"fuse marker written: {_fuse_marker()} (failures={fail_count})")


def _write_fuse_alert() -> None:
    """熔断触发时经既有告警通道（AdminStore）产出 critical 告警。

    supervisor 是独立进程，写告警需把 .fenix/（FENIX_DIR）加入 sys.path 并实例化
    AdminStore；core 包经 .fenix/core → 框架 core/ 软链解析，项目布局缺该软链时
    导入失败。import/写入失败降级为日志（熔断标记与 supervisor.log critical 记录
    已落盘，告警是增强通道）。测试可用替身注入替换。
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
    except ImportError as e:  # 多为布局缺软链：给出排障指引
        log(
            f"fuse alert write failed (non-blocking): {e}"
            f"（导入失败：检查 {FENIX_DIR / 'core'} 软链是否指向框架 core/）"
        )
    except Exception as e:  # noqa: BLE001 — 告警通道非关键路径，失败降级日志
        log(f"fuse alert write failed (non-blocking): {e}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_shutdown_drain_seconds() -> int:
    """读取项目级 .fenix/config.yaml 的 admin.shutdown_drain_seconds（D2）。

    解析失败（文件缺失/非 YAML/字段缺失/非法值）回退 0 —— 调用方按
    ``0 = 现行快速停机`` 语义回退 DEFAULT_SIGKILL_WAIT_SECONDS，保持向后兼容。

    已知限制（code-review 7be89eb40a71）：本函数只读**项目级**
    .fenix/config.yaml，不与用户级 ~/.fenix/config.yaml 深合并——与 daemon 侧
    ``_shutdown_drain_seconds``（经 ConfigLoader.resolve_config 合并读取、
    缺省 1800）配置源不同。admin.shutdown_drain_seconds 只配在用户级时，
    daemon 按合并值排水而本侧按「缺失回退 0」走 60s SIGKILL 等待，排水会被
    截断；daemon 启动自检 ``_check_supervisor_drain_consistency`` 的 WARNING
    文案已指向该限制。未收敛同源的原因：合并读取（含 1800 缺省）会改变
    「项目级未配置 → 60s」既有契约，且使 TestSupervisorWait 的回退断言依赖
    宿主用户级配置（conftest 不隔离 HOME），影响面大于收益，先以标注 +
    自检指向缓解。
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
    except Exception as e:
        # 其余解析/读取异常（YAML 损坏、非法值、权限等）同样按契约回退 0，
        # 但须留观测痕迹——否则排水窗口被无声截断且 supervisor.log 零线索
        log(f"解析 {cfg_path} 的 admin.shutdown_drain_seconds 失败，回退 0 (non-blocking): {e}")
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
    if _atomic_write_json(
        _supervisor_runtime_file(), data, ".supervisor_runtime.", "supervisor_runtime"
    ):
        log(
            f"supervisor_runtime written: sigkill_wait={data['sigkill_wait']}s, "
            f"started_at={data['started_at']}, pid={data['pid']}"
        )


def start_daemon():
    """启动 daemon 子进程（经 .fenix/fenixd.py 软链，保持其 FENIX_DIR 解析正确）。

    写 daemon_started 标记与 Popen 均包 OSError 保护：.fenix 只读/磁盘满等
    异常不再炸穿 main 循环致看门狗无痕退出（daemon 此后永无人拉起）。标记
    写失败仅记日志继续拉起；Popen 失败则删除刚写的伪时间戳（避免 admin/monitor
    误判重启已生效）并返回 None，由调用方按启动失败计数。
    """
    # 原子写口径与 fuse marker / supervisor_runtime / daemon_runtime 统一
    # （code-review 3f99b6283270）：失败已由 _atomic_write_text 记日志，
    # 非阻塞继续拉起（读侧 admin/monitor 以该文件判定重启是否生效）。
    _atomic_write_text(
        DAEMON_STARTED, _now_iso() + "\n", ".daemon_started.", "daemon_started"
    )
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


# ── 遗留 daemon 收编（SIGKILL supervisor 后重启的双 daemon / 误熔断防护）──────
# SIGTERM/SIGINT 有转发收尾（见下方停机信号一节），SIGKILL 无法捕获：supervisor
# 被 SIGKILL 后旧 daemon 仍存活，新 supervisor 启动时无条件 start_daemon——daemon
# 有单例守卫时新 daemon 秒退被误计启动失败、连计 3 次触发熔断 critical 误告警
# （服务实际健康），无守卫时双 daemon 并发写 .fenix。故 daemon 拉起成功后把 pid
# 原子记录到 .fenix/daemon_runtime.json（supervisor 被杀后唯一存活的线索），拉起
# 前先检测收编。路径在调用时经 FENIX_DIR 解析（_fuse_marker 同款），测试注入随动。


def _daemon_runtime_file() -> Path:
    return FENIX_DIR / "daemon_runtime.json"


def _proc_starttime(pid: int):
    """读 /proc/<pid>/stat 的进程启动时刻（字段 22，系统启动后的时钟节拍数）。

    pid 回收精判用（code-review cf31d38b22a1）：pid 被复用后新进程的 starttime
    必然不同（内核单调递增），据此可判定 daemon_runtime.json 记录的 pid 是否
    仍是当年拉起的那个 daemon 进程。comm 字段（第 2 项）可含空格/括号，故以
    最后一个 ')' 切开，其后首项为 state（字段 3），starttime 相对索引 19。
    读取失败（进程已退 / 非 Linux / 权限）返回 None。
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_bytes()
        fields = stat.rsplit(b")", 1)[1].split()
        return int(fields[19])
    except (OSError, ValueError, IndexError):
        return None


def _write_daemon_runtime(pid: int) -> None:
    """daemon 拉起成功后原子记录其 pid（temp + rename，供重启后收编检测）。

    写入失败降级日志：收编检测退化为旧行为（无条件拉起），不炸穿主循环。
    proc_starttime（code-review cf31d38b22a1）：写盘时一并记录该进程的
    /proc/<pid>/stat 启动时刻，收编侧据此精判 pid 是否被回收复用（读取失败
    省略该键，收编侧回退既有 cmdline 宽松校验，见 _adopt_leftover_daemon）。
    """
    data = {"pid": pid, "started_at": _now_iso()}
    starttime = _proc_starttime(pid)
    if starttime is not None:
        data["proc_starttime"] = starttime
    _atomic_write_json(
        _daemon_runtime_file(), data, ".daemon_runtime.", "daemon_runtime"
    )


def _pid_alive(pid: int):
    """os.kill(pid, 0) 存活探查三态：True 存活 / False 已退出 / None 权限受限。

    code-review 15557c8e364a：进程存在但属其它用户（或容器 uid 边界）时
    os.kill(pid, 0) 抛 PermissionError（EPERM）。若与 ESRCH 一并按 OSError
    「进程不存在」处理，会跳过收编随后无条件拉起 → 双 daemon 并发写 .fenix，
    与「宁可多等不双拉」的保守取向相悖。故两态须由调用方区分处置。
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None
    return True


def _adopt_leftover_daemon() -> None:
    """拉起新 daemon 前收编 SIGKILL 遗留的存活旧 daemon（先收编再拉起）。

    读 daemon_runtime.json 记录的 pid：文件缺失/损坏按无旧 daemon 处理；
    os.kill(pid, 0) 报进程不存在（ESRCH，正常重启路径）同样跳过。EPERM（存活
    但属其它用户/uid 边界，code-review 15557c8e364a）按存活保守处理：收编
    序列中信号被拒时等待 sigkill_wait 超时后放行拉起（跳过收编立即拉起会
    双 daemon）。存活则按既有
    停止路径同款 SIGTERM → 等待（sigkill_wait 窗口）→ 超时 SIGKILL 收编，
    等待与收编均不计入启动失败熔断。pid 回收误判（存活但非 daemon）优先比对
    daemon_runtime.json 记录的 /proc/<pid>/stat 启动时刻（proc_starttime，
    code-review cf31d38b22a1：starttime 内核单调，pid 被编辑器/tail 等无关
    进程复用后必然不同，不再误发 SIGTERM/SIGKILL）；记录缺失（旧版 runtime
    文件 / 写盘时读取失败）回退 cmdline 含 fenixd 字样的宽松校验（仅缓解），
    cmdline 不可读按存活保守处理（宁可多等不双拉）。os.kill(pid, 0) 对
    zombie 仍返回真，但旧 supervisor 死后 daemon 已 re-parent 由 init 收尸，
    本进程通常见不到 zombie，不特判。
    """
    try:
        data = json.loads(_daemon_runtime_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    pid = data.get("pid") if isinstance(data, dict) else None
    if not isinstance(pid, int) or pid <= 0:
        return
    alive = _pid_alive(pid)
    if alive is False:
        return
    if alive is None:
        # EPERM：进程存在但不可发信号（其它用户 / 容器 uid 边界）。按已死亡
        # 跳过收编随后无条件拉起 → 双 daemon 并发写 .fenix，恰是本函数要防的
        # 场景；按存活保守处理（宁可多等不双拉），收编序列中信号被拒时在
        # sigkill_wait 超时后放行拉起。
        log(
            f"daemon_runtime pid {pid} probe EPERM (alive, other uid?) "
            "— adopt conservatively"
        )
    recorded_starttime = data.get("proc_starttime")
    if isinstance(recorded_starttime, int):
        # 仅现读不等（可实锤 pid 复用）才跳过收编。现读为 None（code-review
        # 158644d95b99：恰在本窗口退出 / stat 不可读但仍存活，两种解释无法
        # 区分）不据此 skip——存活而不可读时跳过收编、主循环随即无条件拉起
        # 正是本函数要防的双 daemon，与 EPERM 分支「宁可多等不双拉」同款
        # 取向，落入收编序列：进程已退则 SIGTERM 立即 ProcessLookupError
        # 返回（无延迟亦无误杀），仍存活则被正常收编。
        now_starttime = _proc_starttime(pid)
        if now_starttime is not None and now_starttime != recorded_starttime:
            log(
                f"daemon_runtime pid {pid} alive but start time mismatch "
                "(pid reuse) — skip adopt"
            )
            return
    else:
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
            if b"fenixd" not in cmdline:
                log(f"daemon_runtime pid {pid} alive but not fenixd (pid reuse) — skip adopt")
                return
        except OSError:
            log(f"daemon_runtime pid {pid} alive, cmdline unreadable — adopt conservatively")
        # code-review c6ac6582df44：proc_starttime 记录缺失（旧版 runtime /
        # 写盘时 /proc 读取失败省略）时，SIGKILL 升级前无 starttime 可比对，
        # pid 在 SIGTERM 等待窗内被 cmdline 恰含 fenixd 字样的无关进程复用
        # 会误杀。现读一次 starttime 作会话内基线（须在 SIGTERM 发出前读：
        # 旧 daemon 秒退后 pid 被复用时，SIGTERM 后现读会把复用进程当基线），
        # 供升级前与现值比对；读不到保持缺省，升级前退回 cmdline 复核兜底。
        session_starttime = _proc_starttime(pid)
        if session_starttime is not None:
            recorded_starttime = session_starttime
    log(f"leftover daemon (pid {pid}) detected — SIGTERM before starting a new one")
    term_denied = False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        # 信号被拒（跨 uid，code-review 15557c8e364a）：无法收编，但不立即
        # 放行拉起（双 daemon）——按保守取向等满 sigkill_wait 窗口再放行。
        term_denied = True
        log(f"SIGTERM to pid {pid} denied (EPERM) — waiting out window conservatively")
    sigkill_wait = _sigkill_wait_seconds()
    deadline = time.monotonic() + sigkill_wait
    while True:
        if _pid_alive(pid) is False:
            log(f"leftover daemon (pid {pid}) exited after SIGTERM")
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)
    if term_denied:
        # 信号被拒无法升级 SIGKILL，保守窗口已耗尽 → 放行拉起
        log(f"pid {pid} unresponsive to denied signals — proceeding after {sigkill_wait}s")
        return
    log(
        f"leftover daemon (pid {pid}) did not exit within {sigkill_wait}s "
        "after SIGTERM — SIGKILL"
    )
    # 升级 SIGKILL 前复核 starttime（code-review b5de7929b247）：旧 daemon 可能
    # 恰在 SIGTERM 等待窗内退出且 pid 被系统回收复用，轮询探活会把复用进程
    # 当存活旧 daemon，直接 SIGKILL 会命中无关进程。与首次收编比对同款取向：
    # 现读为 None（已退/不可读）或不等均跳过 SIGKILL（进程已退则无需强杀）。
    # 能走到这里说明 SIGTERM 已发成功（EPERM 早在 term_denied 分支放行），
    # 不存在「存活但 stat 不可读」的 EPERM 例外。
    if isinstance(recorded_starttime, int):
        now_starttime = _proc_starttime(pid)
        if now_starttime is None:
            log(
                f"daemon_runtime pid {pid} gone before SIGKILL "
                "(exited after SIGTERM?) — skip SIGKILL"
            )
            return
        if now_starttime != recorded_starttime:
            log(
                f"daemon_runtime pid {pid} alive but start time mismatch before "
                "SIGKILL (pid reuse) — skip SIGKILL"
            )
            return
    else:
        # code-review c6ac6582df44：会话内基线也未能建立（上面现读 starttime
        # 失败）时，SIGKILL 前至少重读 cmdline 复核仍含 fenixd，避免把等待窗
        # 内被无关进程复用的 pid 强杀。能走到这里说明 SIGTERM 已发成功（无
        # EPERM 例外，同上），cmdline 不可读按已退处理、跳过强杀放行拉起。
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            log(f"daemon_runtime pid {pid} gone or unreadable before SIGKILL — skip SIGKILL")
            return
        if b"fenixd" not in cmdline:
            log(
                f"daemon_runtime pid {pid} alive but not fenixd before "
                "SIGKILL (pid reuse) — skip SIGKILL"
            )
            return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        # SIGKILL 同被拒：sigkill_wait 窗口已耗尽，按保守取向放行拉起
        pass
    # SIGKILL 后短等收尸（与 _terminate_daemon 的 5s 收尸窗口同量级）
    time.sleep(5)


# ── supervisor 自身停机信号（code-review 09d6ed559666）────────────────────
# supervisor 被外部 SIGTERM/SIGINT（系统管理器 stop / 人为 kill）时若直接消亡，
# daemon 会成为孤儿，随后重启 supervisor 又无条件拉起新 daemon → 双 daemon 并发
# 写 .fenix。处理器仅置位停机标记（信号上下文里不做等待/IO），SIGTERM 转发与
# 等待退出由主循环按既有 stop/restart 同款路径完成；SIGKILL 无法捕获，不在
# 本机制的覆盖范围。
_shutdown_requested = False


def _request_shutdown(signum, frame):
    """SIGTERM/SIGINT 处理器：置位停机标记，收尾（转发+等待）由主循环完成。"""
    global _shutdown_requested
    _shutdown_requested = True


def _terminate_daemon(proc, sigkill_wait: int) -> None:
    """监视循环共用收尾：SIGTERM → wait(sigkill_wait) → 超时 SIGKILL → 5s 收尸。

    stop / restart 分支（code-review f9f8e81b6fa5）此前各自内联这段逻辑且逐行
    相同——本脚本的 sigkill 等待窗口出过「只改一处不改另一处」的漂移事故
    （interrupt-recovery-preserve D2），收编为单一实现消除同型风险。分支只保留
    各自的日志文案与 restart 标志；proc 由调用方保证非 None（start_daemon 失败
    分支在进入监视循环前已 continue）。
    """
    try:
        proc.send_signal(signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=sigkill_wait)
    except subprocess.TimeoutExpired:
        log(f"daemon did not exit within {sigkill_wait}s after SIGTERM — SIGKILL")
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # SIGKILL 后仍可能因不可中断睡眠（D 状态）收尸超时，捕获以免异常
            # 炸穿 supervisor 主循环；进程最终退出时由监视循环外的 proc.wait()
            # 收尸。
            log(
                "daemon still alive 5s after SIGKILL "
                "(uninterruptible sleep?) — leave reaping to outer wait"
            )


# ── supervisor 单实例锁（code-review 8b00c1d597c4）────────────────────────
# 锁 fd 保持全局引用，进程生命周期内持有，退出时 OS 自动释放（daemon 侧
# _acquire_singleton_lock 同款形态）。双活 supervisor 的危害链：第二个实例
# 拉起的 daemon 因 daemon 单例锁秒退 → 被按启动失败连计 3 次触发假熔断
# critical 告警（服务实际经第一个 supervisor 健康）；且 _fuse_blocked 按 pid
# 不匹配会删掉第一个 supervisor 的熔断标记，熔断状态被并发方静默清除。在
# 入口排他掉，收编/熔断逻辑不变。
_LOCK_FD = None


def _acquire_supervisor_lock() -> None:
    """获取 supervisor 单实例 flock 排他锁，第二个实例打印提示并退出（非零码）。

    锁文件 .fenix/supervisor.lock，flock 非阻塞排他；持锁 fd 存入全局
    _LOCK_FD 保活至进程退出（中途关闭即放锁）。须在 _write_supervisor_runtime()
    与 start_daemon() 之前调用——第二实例不得覆写首个实例的 runtime 自报、
    不得参与 daemon 拉起/收编。
    """
    global _LOCK_FD
    lock_path = FENIX_DIR / "supervisor.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as e:
        # 锁文件不可用（FENIX_DIR 只读、supervisor.lock 被同名目录占用等）：
        # 与本文件其余 .fenix 写路径同口径降级为可读错误+非零码干净退出，
        # 不裸栈——看门狗无痕死亡意味着 daemon 从此无人拉起。
        print(
            f"FATAL: 无法打开 supervisor 单实例锁文件 {lock_path}: {e}，本实例退出",
            file=sys.stderr,
        )
        log(f"cannot open singleton lock file {lock_path}: {e} — exiting")
        sys.exit(1)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        print(
            f"Fenixd supervisor 已在运行（单实例锁被持有: {lock_path}），本实例退出",
            file=sys.stderr,
        )
        log("another supervisor instance holds the singleton lock — exiting")
        sys.exit(1)
    _LOCK_FD = fd


def main():
    # 启动守卫（fix-supervisor-hosting-chain D1）：解析出的项目根下必须存在
    # .fenix/（目录或指向目录的软链），缺失或为普通文件时打印含解析来源与解析
    # 结果的可读错误并以非零码退出（is_dir() 对两者均假——否则普通文件情形
    # 会在下方 mkdir 抛 FileExistsError 炸穿）；必须在 _write_supervisor_runtime()
    # 与 start_daemon() 之前返回，不产生任何进程、不写入任何 runtime 文件。
    if not FENIX_DIR.is_dir():
        print(
            f"FATAL: supervisor 目标项目根下不存在 .fenix/（或不是目录）（{FENIX_DIR}）。\n"
            f"  解析来源: {PROJECT_ROOT_SOURCE}\n"
            f"  解析结果: {PROJECT_ROOT}\n"
            f"  请确认目标是一个已初始化（/fenix-setup 完成）的 Fenixd 项目，"
            f"并显式指定 --project-root 或在项目根下执行本命令。",
            file=sys.stderr,
        )
        sys.exit(2)
    FENIX_DIR.mkdir(parents=True, exist_ok=True)
    # 单实例锁（code-review 8b00c1d597c4）：先于自报/收编/拉起，双活实例在此退出
    _acquire_supervisor_lock()
    log(f"supervisor starting (pid {os.getpid()}, root {PROJECT_ROOT})")
    # 启动自报：SIGKILL 等待窗口 + 启动时间（fix-daemon-lifecycle-races D2）。
    # daemon 启动一致性自检将读取该文件，缺失/不一致 → WARNING 提示重启 supervisor。
    _write_supervisor_runtime()

    # 停机信号注册（code-review 09d6ed559666）：SIGTERM/SIGINT → 转发给 daemon
    # 并等待退出后再退出，防孤儿 daemon / 重启后双 daemon。
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    # 连续启动失败计数（add-stale-code-selfheal D4）：仅「意外退出」累计，
    # 优雅重启（restart_request）/ 显式停止不计；存活 ≥ 60s 清零。
    fail_count = 0

    while True:
        if STOP_FLAG.exists():
            log("stop flag present — supervisor exiting")
            break

        # supervisor 自身被请求停机（code-review 09d6ed559666）：尚未监视 daemon
        # （启动期/退避期）就收到 SIGTERM/SIGINT → 直接退出，不再拉起新 daemon。
        if _shutdown_requested:
            log("shutdown signal received — supervisor exiting")
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

        # 先收编再拉起（SIGKILL supervisor 后旧 daemon 可能仍存活，见
        # _adopt_leftover_daemon）：避免双 daemon 与启动失败误熔断。
        _adopt_leftover_daemon()

        # 收编等待窗（最长 sigkill_wait+5s）内到达的停机/stop 请求在此复查
        # （code-review 127aca02d9df）：循环开头的检查已过、等待期间标记只被
        # 置位不复查，直接 start_daemon 会闪现一次完整 daemon 启动（单例锁、
        # 启动扫描等副作用照常执行），与停机语义相悖。收编已让旧 daemon 退出，
        # 此处直接退出无孤儿、无双 daemon。
        if STOP_FLAG.exists():
            log("stop flag present — supervisor exiting")
            break
        if _shutdown_requested:
            log("shutdown signal received — supervisor exiting")
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
        # 存活时长用单调钟度量（code-review 682cf36c80ea）：time.time() 遇 NTP
        # 大步回拨/虚拟机迁移恢复时可能倒退，alive_seconds 变负 → 意外退出被
        # 误判为「存活 <60s 窗口」计启动失败，连续 3 次即假熔断。与
        # _adopt_leftover_daemon 等待窗（time.monotonic）同口径。
        started_ts = time.monotonic()
        log(f"daemon started (pid {proc.pid})")
        # 记录 daemon pid（原子覆写）：supervisor 被 SIGKILL 后重启时供
        # _adopt_leftover_daemon 检测收编（写入失败降级日志，不阻断监视）
        _write_daemon_runtime(proc.pid)

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
                _terminate_daemon(proc, _sigkill_wait_seconds())
                break
            if _shutdown_requested:
                # supervisor 自身收到 SIGTERM/SIGINT（code-review 09d6ed559666）：
                # 按既有停止路径转发 SIGTERM 给 daemon 并等待退出后随同退出，
                # 避免孤儿 daemon / 重启 supervisor 后双 daemon。
                log("shutdown signal received — SIGTERM daemon for supervisor exit")
                restart = False
                # 收尾复用 _terminate_daemon 单一实现（同 stop/restart 分支），
                # 避免再内联复制 SIGTERM→wait→SIGKILL→收尸 序列复演漂移
                _terminate_daemon(proc, _sigkill_wait_seconds())
                break
            if RESTART_REQUEST.exists():
                log("restart_request detected — SIGTERM daemon for restart")
                restart = True
                _terminate_daemon(proc, _sigkill_wait_seconds())
                break
            time.sleep(2)

        rc = proc.poll()
        if rc is None:
            # 监视循环内已处理退出，兜底再等
            rc = proc.wait()
        alive_seconds = time.monotonic() - started_ts
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

        # supervisor 自身停机信号（code-review 09d6ed559666）：daemon 已随同
        # 退出 → 不再自动拉起，直接退出（此路径属优雅停机，不计熔断）。
        if _shutdown_requested:
            log("shutdown signal received — supervisor exiting")
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

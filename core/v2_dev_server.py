"""
v2_dev_server.py — per-run 隔离测试服务生命周期管理（add-worktree-test-server）。

框架在派发 implementer/verifier 进入 worktree 前，于 worktree 内启动专属测试
服务（dev-server.mjs）：静态资源由 worktree 副本提供，后端 API/SSE 反代至主
服务 8787。端口按确定性策略分配（V2_TEST_PORT_BASE + run序号 mod 区间），冲突
重试；run 终态后框架回收进程。

本模块只负责：端口分配、dev-server.mjs 子进程启停、V2_BASE_URL 注入值计算、
遗留进程清扫（daemon 启动时）。dev-server.mjs 自身实现见 tests/v2/dev-server.mjs。
"""

import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

from core.proc_utils import find_free_port, is_claude_process

# ── 端口分配（design D3）──────────────────────────────────────────────
# 确定性端口段：V2_TEST_PORT_BASE 起、连续 V2_TEST_PORT_RANGE 个高位端口。
# 主服务 8787 与常见服务不在该段内；并发运行（并行度 2，预留余量取 20）不冲突。
V2_TEST_PORT_BASE = 19000
V2_TEST_PORT_RANGE = 20

# dev-server 孤儿自灭轮询间隔（秒）：与 tests/v2/dev-server.mjs 的 ppid 绑定
# 轮询间隔对齐（design D3），供测试/日志引用同一语义值。
PPID_POLL_INTERVAL = 2

# 子进程命令行标记（D2 清扫依据）：daemon 重启时扫 pgrep 该字面量识别遗留 dev-server。
V2_DEV_SERVER_MARKER = "fenix-v2-dev-server"


class V2DevServerError(Exception):
    """dev-server 启动/重试耗尽失败。"""


def _dev_server_script() -> Path:
    """dev-server.mjs 绝对路径（tests/v2/dev-server.mjs）。"""
    # 本文件位于 core/，相对上一层 tests/v2/dev-server.mjs
    return Path(__file__).absolute().parent.parent / "tests" / "v2" / "dev-server.mjs"


def _node_bin() -> str:
    """返回 node 可执行文件路径：优先 PATH 中 node，无则回退常见绝对路径。"""
    import shutil

    found = shutil.which("node")
    if found:
        return found
    for cand in ("/usr/bin/node", "/usr/local/bin/node"):
        if Path(cand).exists():
            return cand
    return "node"


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """TCP 探测端口是否可监听（被占用则 listen 失败）。

    design D5：bind 前设置 SO_REUSEADDR，消除 TIME_WAIT 状态（对端关闭后
    残留等待复用的半开连接）造成的假性占用——否则短轮换的后端会把刚关的
    端口误判为被占、确定性端口段在事故后持续空转。
    """
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def allocate_port(
    run_seq: int,
    used_ports: Optional[set] = None,
    max_retries: int = V2_TEST_PORT_RANGE,
    logger=None,
) -> int:
    """按确定性策略分配一个空闲端口（design D3）。

    Args:
        run_seq: 运行序号（单调递增），决定首选端口；并发运行传入不同序号自然分散。
        used_ports: 本进程已分配、尚在使用的端口集合（避免同 daemon 内重复分配）。
        max_retries: 冲突时向后尝试的最大端口数（默认覆盖整个端口段）。
        logger: 可选日志器（含 info/warning/error）。

    Returns: 空闲端口号。

    design D5：端口段（19000-19019）全部被真实 listener 占满时**不再抛
    V2DevServerError 终止验证**，改为回退系统临时端口（find_free_port）并
    WARNING 留痕。宁用随机端口也绝不静默回退 8787 主树常驻实例——那是
    09-05 已实证的「旧码污染验证」形态。
    """
    used_ports = used_ports or set()
    for offset in range(max_retries):
        port = V2_TEST_PORT_BASE + ((run_seq + offset) % V2_TEST_PORT_RANGE)
        if port in used_ports:
            continue
        if _port_in_use(port):
            continue
        return port
    try:
        fallback = find_free_port()
    except OSError as e:
        # 临时端口申请极端情况下也可抛 OSError（如 fd 耗尽）；包装为契约异常，
        # 避免绕过 start() 声明的 V2DevServerError 契约直抛调用方。
        raise V2DevServerError(f"ephemeral port fallback failed: {e}") from e
    if logger:
        logger.warning(
            "v2_dev_server",
            f"V2 test port segment exhausted: base={V2_TEST_PORT_BASE} "
            f"range={V2_TEST_PORT_RANGE}, used={sorted(used_ports)} — "
            f"falling back to ephemeral port {fallback}. "
            f"既有拦截性回退已封死（绝不回退主树 8787）",
        )
    return fallback


def start(
    wt_path: Path, run_seq: int, used_ports: Optional[set] = None, logger=None
) -> Tuple[int, subprocess.Popen]:
    """在 worktree 内启动 dev-server.mjs，返回 (port, proc)。

    Args:
        wt_path: worktree 路径（静态根取 <wt_path>/core/dashboard/static）。
        run_seq: 运行序号，决定首选端口。
        used_ports: 本进程已占用端口集合（in/out：成功分配后写入）。
        logger: 可选日志器（含 info/warning/error）。

    Raises: V2DevServerError: 端口分配或启动失败。
    """
    static_root = Path(wt_path) / "core" / "dashboard" / "static"
    if not static_root.is_dir():
        # worktree 可能未含 core/dashboard/static（罕见）；回退主树静态根，
        # 保证服务能起，但失去 worktree 隔离意义——仅作兜底不阻断派发。
        wt_static_root = static_root
        static_root = Path(__file__).absolute().parent.parent / "core" / "dashboard" / "static"
        if not static_root.is_dir():
            # 两处静态根同时缺失（如非常规 checkout 布局）：把失败提前到启动期，
            # 避免服务对任意路径 404、报错推迟到验证场景阶段且与根因脱节。
            raise V2DevServerError(
                f"static root missing in both worktree ({wt_static_root}) "
                f"and main tree ({static_root})"
            )
        if logger:
            logger.warning(
                "v2_dev_server",
                f"worktree static root missing, fallback to main tree: {static_root}",
            )

    try:
        # design D5：allocate_port 不再抛 V2DevServerError（耗尽回退临时端口）；
        # 保留防御性捕获，覆盖未来新增异常形态。
        port = allocate_port(run_seq, used_ports, logger=logger)
    except V2DevServerError as e:
        if logger:
            logger.error("v2_dev_server", f"port allocation failed: {e}")
        raise

    script = _dev_server_script()
    if not script.is_file():
        raise V2DevServerError(f"dev-server.mjs not found: {script}")

    # 把标记字面量写入 argv，使 daemon 重启后 pgrep -f 能按完整命令行识别该子进程
    # （标记不写入 .mjs 源码，避免干扰脚本自身参数解析）。见 cleanup_orphans。
    cmd = [
        _node_bin(),
        str(script),
        str(static_root),
        str(port),
        V2_DEV_SERVER_MARKER,
    ]
    env = dict(os.environ)
    # 先剥离环境中已有的 --max-old-space-size=... 片段再追加，确保内存钳制
    # 取本框架设定值（不依赖 node 对重复选项的取舍行为）。
    env["NODE_OPTIONS"] = (
        re.sub(r"--max-old-space-size=\S+", "", env.get("NODE_OPTIONS", ""))
        + " --max-old-space-size=256"
    ).strip()

    def _log(level, msg):
        if logger:
            getattr(logger, level)("v2_dev_server", msg)

    try:
        # design D2（进程组杀树）：start_new_session=True 使 dev-server 独立进程组
        # （setsid），停止时 killpg 杀整棵进程树，杜绝「只杀 shell 不杀孙进程」。
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
            # 标记写入 argv[0] 不可靠；用 cwd + marker 文件不便，改由 pgrep 匹配
            # 完整 cmdline（含 "fenix-v2-dev-server" 字面量）。见 cleanup_orphans。
        )
    except OSError as e:
        raise V2DevServerError(f"failed to spawn dev-server: {e}")

    # 等待端口就绪（dev-server.mjs 监听后即写 "listening"；不读 stdout 时用探测）。
    # 连通成功后还须做实例身份收口：allocate_port 的 bind 探测与 node 实际 bind
    # 之间存在窗口，端口可能被他方进程抢注——node bind 失败（已退出或僵而未死）
    # 时 connect 握手由他方 listener 应答，仅凭连通会误判就绪、把验证流量打到
    # 异码服务上。同一 addr:port 的 LISTEN socket 唯一（node 未用 SO_REUSEPORT），
    # 核对端口 LISTEN inode 是否归属本进程 /proc/<pid>/fd 即可确定性判定应答者
    # 身份，取代「延迟数百毫秒再看存活」的时长启发式（进程存活≠端口归它）。
    ready = _wait_ready(port, timeout=5.0, logger=logger) and _port_listened_by(
        port, proc
    )
    if not ready:
        # 启动但端口未就绪/端口非本进程持有：视为失败，回收子进程，按端口冲突重试语义上抛。
        _log("error", f"dev-server on port {port} not ready or port not served by it, killing")
        _kill(proc)
        raise V2DevServerError(f"dev-server on port {port} failed to become ready")

    if used_ports is not None:
        used_ports.add(port)
    _log("info", f"dev-server started pid={proc.pid} port={port} " f"static={static_root}")
    return port, proc


def _wait_ready(port: int, timeout: float = 5.0, logger=None) -> bool:
    """轮询端口是否可连接（dev-server 监听成功即返回）。"""
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            time.sleep(0.1)
        finally:
            s.close()
    return False


def _listen_inode(port: int) -> Optional[str]:
    """取 port 当前 LISTEN socket 的 inode（/proc/net/tcp[6]；无监听返回 None）。

    /proc/net/tcp 固定布局：local_address 形如 0100007F:4A38（IP:十六进制
    端口）、第 4 列 st=0A 即 LISTEN、第 10 列为 socket inode。
    """
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            fields = row.split()
            try:
                if fields[3] == "0A" and int(fields[1].rsplit(":", 1)[1], 16) == port:
                    return fields[9]
            except (IndexError, ValueError):
                continue
    return None


def _port_listened_by(port: int, proc: subprocess.Popen, timeout: float = 2.0) -> bool:
    """核对 port 上的 LISTEN socket 是否归属 proc（就绪判定的实例身份收口）。

    _wait_ready 只证明「有 listener 应答」；若 allocate_port 的 bind 探测与
    node 实际 bind 之间端口被抢注，应答者是他方进程、验证流量会打到异码服务。
    同一 addr:port 不可能存在两个 LISTEN（node 未用 SO_REUSEPORT），故端口
    LISTEN inode 出现在 proc 的 /proc/<pid>/fd 即证明应答者就是本实例，判定
    与进程退出时机无关。就绪即命中通常首轮通过；短暂重试仅覆盖 node 尚在
    bind 的窗口与 procfs 瞬时读失败，proc 已退出（bind 失败自灭）则立即判负。
    """
    deadline = time.time() + timeout
    while True:
        if proc.poll() is not None:
            return False
        inode = _listen_inode(port)
        if inode is not None:
            try:
                fds = Path(f"/proc/{proc.pid}/fd").iterdir()
                if any(os.readlink(fd) == f"socket:[{inode}]" for fd in fds):
                    return True
            except OSError:
                pass
        if time.time() >= deadline:
            return False
        time.sleep(0.1)


def _kill(proc: subprocess.Popen) -> None:
    """终止 dev-server 子进程（进程组 SIGTERM→等待→SIGKILL→单进程兜底）。

    design D2（进程组杀树）：dev-server spawn 于独立进程组（start_new_session），
    停止按 killpg 终止整棵进程树——shell/npm 包装形态下孙进程一并终止，杜绝
    「只杀 shell 不杀孙进程」。全程 try/except 包裹：进程恰好死亡引发
    ProcessLookupError 时按已终止处理（竞态安全）。
    """
    if proc.poll() is not None:
        return
    pid = proc.pid
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        pgid = None
    # 1) 进程组 SIGTERM → 等待退出
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.wait(timeout=5)
            # 组长虽按时退出，组内仍可能有忽略 SIGTERM 的组员（shell/npm 包装
            # 链形态），返回前对进程组补一次 SIGKILL 收尾，确保「杀整棵树」
            # 成立；组已空（全员随 SIGTERM 退出）抛 ProcessLookupError，属
            # 常态按已清算处理。
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
            return
        except subprocess.TimeoutExpired:
            pass
        except OSError:
            return
    # 2) 进程组 SIGKILL → 等待退出（宽限期后仍无响应的残留强制终止）
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        except OSError:
            return
    # 3) 单进程兜底（进程组判定失败或极端未退净）
    if proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
        except OSError:
            pass


def stop(
    proc: subprocess.Popen,
    port: Optional[int] = None,
    used_ports: Optional[set] = None,
    logger=None,
) -> None:
    """回收一个 dev-server 进程并释放端口（D2 终态回收）。"""
    _kill(proc)
    if port is not None and used_ports is not None:
        used_ports.discard(port)
    if logger:
        logger.info("v2_dev_server", f"dev-server stopped pid={proc.pid} port={port}")


def base_url(port: int) -> str:
    """构造注入 agent 运行环境的 V2_BASE_URL。"""
    return f"http://127.0.0.1:{port}"


def _pgrep_dev_servers(pattern: str) -> list:
    """pgrep -f 匹配 cmdline，返回 PID 列表（pgrep 不可用/超时返回空）。"""
    try:
        res = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if res.returncode != 0 or not res.stdout.strip():
        return []
    return [int(s) for s in res.stdout.split() if s.strip().isdigit()]


def _pid_alive(pid: int) -> bool:
    """进程是否仍存活（/proc 条目存在且非僵尸态；Z 态视同已终止）。

    孤儿 dev-server 的父进程（已死 daemon 的 shell 链）可能不收尸，/proc
    条目以 Z 态残留，须按已终止计，否则误补 SIGKILL 且漏计清理数。
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_bytes()
        # comm 可含空格/括号，取最后一个 ')' 之后的首字段（state）。
        return stat.rsplit(b")", 1)[1].split()[:1] != [b"Z"]
    except (OSError, IndexError):
        return False


def _pid_recently_started(pid: int, grace_seconds: float = 60.0) -> bool:
    """进程启动时刻距现在是否不足 grace_seconds（/proc 目录 mtime 作近似）。

    Linux /proc/<pid> 目录的 mtime 即该 PID 当前进程的创建时刻，可作启动
    时刻近似（秒级误差可接受）；读取失败（进程已消失等）按不豁免计。
    """
    try:
        started_at = os.stat(f"/proc/{pid}").st_mtime
    except OSError:
        return False
    return (time.time() - started_at) < grace_seconds


def _kill_pids(pids: list, logger=None) -> int:
    """对 PID 列表逐个 SIGTERM，短暂轮询 /proc 确认退出，仍存活补 SIGKILL。

    与 _kill 同走 os.kill 信号直发，不经外部 kill 二进制（其缺失会使清扫
    静默退化为空操作）。返回确认已终止的进程数（单个 pid 操作失败——权限
    不足/竞态消失——按未终止计，忽略继续）。等待有界：SIGTERM 后至多 ~2s、
    SIGKILL 后至多 ~1s，不阻塞调用方（启动清扫/周期清扫均可容忍秒级）。
    """
    killed = 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue  # 恰已退出（竞态），按未终止计
        except OSError as e:
            if logger:
                logger.warning(
                    "v2_dev_server",
                    f"orphan sweep: SIGTERM pid={pid} failed ({e}) — skipped",
                )
            continue
        for _ in range(20):  # ~2s 上限等待 SIGTERM 生效
            if not _pid_alive(pid):
                break
            time.sleep(0.1)
        else:  # 仍存活（如 node 卡死不响应 SIGTERM）→ SIGKILL 兜底
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass  # 竞态消失/权限不足，交由末尾 _pid_alive 判定
            for _ in range(10):  # ~1s 上限等待 SIGKILL 生效
                if not _pid_alive(pid):
                    break
                time.sleep(0.1)
        if not _pid_alive(pid):
            killed += 1
    return killed


def _dev_server_worktree_root(tokens: list) -> Optional[Path]:
    """从 dev-server argv 解析其归属 worktree 根；不携带 worktree 路径返回 None。

    argv 形如 ``[node, dev-server.mjs, <wt>/core/dashboard/static, <port>, ...]``。
    以静态根 token（含 ``/core/dashboard/static`` 尾缀）为**权威归属**：脚本自身
    路径在框架运行于 worktree 内时（本仓库以 worktree 为开发态时）同样含
    ``/worktrees/``，若按首个命中会误把脚本路径解析为归属 worktree。
    """
    for t in tokens:
        if not t.startswith("/") or "/core/dashboard/static" not in t:
            continue
        if "/worktrees/" not in t:
            continue
        # rsplit 取末段（修复验证轮 BUG）：框架 worktree 内跑 pytest 时
        # basetemp 位于 <framework-wt>/.fenix/pytest-basetemp，测试 worktree
        # 的静态根路径含两段 /worktrees/（框架段 + 测试段），split 取首段会
        # 把归属误判为框架 worktree 自身（其含存活 claude 进程 → 误豁免，
        # 孤儿判定落空）。worktree 名以路径末段为准。
        prefix, rest = t.rsplit("/worktrees/", 1)
        wt_name = rest.split("/", 1)[0]
        if wt_name:
            return Path(prefix) / "worktrees" / wt_name
    return None


def _worktree_has_live_referencing_process(wt_root: Path, exclude_pid: int) -> bool:
    """进程表中是否存在（除 dev-server 自身外）引用该 worktree 的**存活 claude 进程**。

    attempt 的 claude 进程经 --add-dir 引用 worktree 目录；dev-server 自身
    cmdline 也含该路径，需排除，否则永远「存活」。

    design D4（豁免过滤修复）：有效豁免**必须**以 claude 进程为锚——否则同一
    worktree 的两个孤儿 dev-server 互为"存活引用"互相豁免、永不清扫（09-04/05
    事故根因之一）。与 worktree_manager._worktree_has_live_process 同判定。
    """
    try:
        # 尾边界防串扰：pgrep -f 按子串 ERE 匹配，worktree 名 foo 会连引用
        # worktrees/foo-bar 的进程一并命中（跨 worktree 误豁免）；须后随
        # /、空白或行尾才算引用本 worktree。名含正则元字符时 re.escape
        # 免被当作模式语法解释。
        res = subprocess.run(
            [
                "pgrep",
                "-f",
                rf"worktrees/{re.escape(wt_root.name)}(/|[[:space:]]|$)",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    if res.returncode != 0 or not res.stdout.strip():
        return False
    return any(
        int(s) != exclude_pid and is_claude_process(s)
        for s in res.stdout.split()
        if s.strip().isdigit()
    )


def _dev_server_orphan_pids(logger=None) -> list:
    """识别孤儿 dev-server PID：worktree 已消失，或无任何存活进程归属。

    背景（admin 处置 v2-alerts-activities）：孤儿 dev-server 的 argv 残留已删除
    worktree 的路径，被 worktree_manager 的 pgrep 存活探测误判为持锁 attempt
    → spec 锁永不释放 → 派发滞留（dispatch_stalled）。反向缺陷同样要防：
    无差别按标记清理会误杀 daemon 重启时仍在服务的活跃 run dev-server。
    故以「worktree 存在 且 有存活归属进程」为豁免条件，两条都检查。
    另设启动宽限豁免：启动不足 60s 的 dev-server 本轮一律跳过（派发先启
    dev-server、再 spawn claude 的秒级窗口内归属探测必然落空，防周期清扫
    TOCTOU 误杀在服 run）。
    """
    out = []
    for pid in _pgrep_dev_servers(V2_DEV_SERVER_MARKER):
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            tokens = [a.decode("utf-8", "replace") for a in argv if a]
        except OSError:
            continue
        wt_root = _dev_server_worktree_root(tokens)
        if wt_root is None:
            # 不携带 worktree 路径（如 start() 主树静态根回退形态）：argv 无归属
            # 可探测，按虚构路径反查 pgrep 恒落空（恒判孤儿、误杀在服 run）。
            # 归属 attempt 的 claude 进程经 --add-dir 引用 worktree 路径，无法从
            # argv 反推，故无安全探测面——保守跳过清扫并 WARNING 留痕，交由运维
            # 判别处置（该形态罕见，且 dev-server 仍有 ppid 绑定自灭兜底）。
            static_root = next(
                (t for t in tokens if "/core/dashboard/static" in t), "")
            if logger:
                logger.warning(
                    "v2_dev_server",
                    f"orphan sweep skipped for pid={pid}: argv carries no "
                    f"worktree path (static_root={static_root or 'unknown'}) "
                    f"— 未清扫的存量 dev-server（主树静态根回退形态），"
                    f"确认无活跃 run 后可手动 kill",
                )
            continue
        if wt_root.is_dir() and _worktree_has_live_referencing_process(wt_root, pid):
            continue  # 归属存活 attempt，保留
        # 启动宽限豁免（TOCTOU 防误杀）：框架派发先启 dev-server、再 spawn
        # claude（agent_runner D2），dev-server 落地到 claude 进程以 --add-dir
        # 形式出现在 pgrep 结果存在秒级窗口；周期清扫（fenixd.py 每 600s 一次）
        # 恰落该窗口时归属探测落空 → 误杀在服 run 的 dev-server（已注入的
        # V2_BASE_URL 指向死端口，验证轮伪失败）。故启动不足 60s 的进程本轮
        # 一律跳过，交由下一轮周期清扫再判：漏清代价仅为短暂延迟（dev-server
        # 另有 ppid 绑定自灭兜底），远低于误杀在服 run。
        if _pid_recently_started(pid):
            if logger:
                logger.info(
                    "v2_dev_server",
                    f"orphan sweep skipped for pid={pid}: started <60s ago "
                    f"（派发启动窗口豁免，防归属探测 TOCTOU 误杀）",
                )
            continue
        out.append(pid)
    return out


def cleanup_orphans(logger=None) -> int:
    """daemon 启动时清扫遗留 dev-server（D2）：无存活归属的 dev-server 进程。

    判定（admin 处置 v2-alerts-activities 加固，取代纯标记匹配）：
    dev-server argv 携带 worktree 路径，据此判断其归属——worktree 已消失、
    或进程表中无该 worktree 的存活归属进程（attempt 已死而 server 残留）→
    孤儿，回收；归属存活 attempt → 保留（daemon 重启可能先于子进程结束）。
    防止残留进程被 worktree_manager 的 pgrep 存活探测误判为持锁 attempt。
    argv 不携带 worktree 路径（主树静态根回退形态）→ 无归属可探测，保守
    跳过并 WARNING 留痕（误杀在服 run 比漏清罕见残留代价更高）。

    Returns: 被终止的进程数。
    """
    pids = sorted(set(_dev_server_orphan_pids(logger=logger)))
    if not pids:
        return 0
    killed = _kill_pids(pids, logger=logger)
    if killed and logger:
        logger.warning("v2_dev_server", f"cleaned up {killed} orphan dev-server(s)")
    return killed

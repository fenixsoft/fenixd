"""
v2_dev_server.py — per-run 隔离测试服务生命周期管理（add-worktree-test-server）。

框架在派发 implementer/verifier 进入 worktree 前，于 worktree 内启动专属测试
服务（dev-server.mjs）：静态资源由 worktree 副本提供，后端 API/SSE 反代至主
服务 8787。端口按确定性策略分配（V2_TEST_PORT_BASE + run序号 mod 区间），冲突
重试；run 终态后框架回收进程。

本模块只负责：端口分配、dev-server.mjs 子进程启停、V2_BASE_URL 注入值计算、
遗留进程清扫（daemon 启动时）。dev-server.mjs 自身实现见 tests/v2/dev-server.mjs。
"""

import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── 端口分配（design D3）──────────────────────────────────────────────
# 确定性端口段：V2_TEST_PORT_BASE 起、连续 V2_TEST_PORT_RANGE 个高位端口。
# 主服务 8787 与常见服务不在该段内；并发运行（并行度 2，预留余量取 20）不冲突。
V2_TEST_PORT_BASE = 19000
V2_TEST_PORT_RANGE = 20

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
    """TCP 探测端口是否可监听（被占用则 listen 失败）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def allocate_port(run_seq: int,
                  used_ports: Optional[set] = None,
                  max_retries: int = V2_TEST_PORT_RANGE) -> int:
    """按确定性策略分配一个空闲端口（design D3）。

    Args:
        run_seq: 运行序号（单调递增），决定首选端口；并发运行传入不同序号自然分散。
        used_ports: 本进程已分配、尚在使用的端口集合（避免同 daemon 内重复分配）。
        max_retries: 冲突时向后尝试的最大端口数（默认覆盖整个端口段）。

    Returns: 空闲端口号。

    Raises: V2DevServerError: 整段端口均被占用。
    """
    used_ports = used_ports or set()
    for offset in range(max_retries):
        port = V2_TEST_PORT_BASE + ((run_seq + offset) % V2_TEST_PORT_RANGE)
        if port in used_ports:
            continue
        if _port_in_use(port):
            continue
        return port
    raise V2DevServerError(
        f"V2 test port exhausted: base={V2_TEST_PORT_BASE} "
        f"range={V2_TEST_PORT_RANGE}, used={sorted(used_ports)}"
    )


def start(wt_path: Path, run_seq: int,
          used_ports: Optional[set] = None,
          logger=None) -> Tuple[int, subprocess.Popen]:
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
        static_root = Path(__file__).absolute().parent.parent / "core" / "dashboard" / "static"
        if logger:
            logger.warning(
                "v2_dev_server",
                f"worktree static root missing, fallback to main tree: {static_root}",
            )

    try:
        port = allocate_port(run_seq, used_ports)
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
    env = dict(__import__("os").environ)
    env["NODE_OPTIONS"] = (env.get("NODE_OPTIONS", "") + f" --max-old-space-size=256").strip()

    def _log(level, msg):
        if logger:
            getattr(logger, level)("v2_dev_server", msg)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            # 标记写入 argv[0] 不可靠；用 cwd + marker 文件不便，改由 pgrep 匹配
            # 完整 cmdline（含 "fenix-v2-dev-server" 字面量）。见 cleanup_orphans。
        )
    except OSError as e:
        raise V2DevServerError(f"failed to spawn dev-server: {e}")

    # 等待端口就绪（dev-server.mjs 监听后即写 "listening"；不读 stdout 时用探测）。
    if not _wait_ready(port, timeout=5.0, logger=logger):
        # 启动但端口未就绪：视为失败，回收子进程，按端口冲突重试语义上抛。
        _log("error", f"dev-server on port {port} not ready in 5s, killing")
        _kill(proc)
        raise V2DevServerError(
            f"dev-server on port {port} failed to become ready"
        )

    if used_ports is not None:
        used_ports.add(port)
    _log("info", f"dev-server started pid={proc.pid} port={port} "
                 f"static={static_root}")
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


def _kill(proc: subprocess.Popen) -> None:
    """终止 dev-server 子进程（SIGTERM→短暂等待→SIGKILL 兜底）。"""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def stop(proc: subprocess.Popen,
         port: Optional[int] = None,
         used_ports: Optional[set] = None,
         logger=None) -> None:
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
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    if res.returncode != 0 or not res.stdout.strip():
        return []
    return [int(s) for s in res.stdout.split() if s.strip().isdigit()]


def _kill_pids(pids: list) -> int:
    """对 PID 列表逐个 SIGTERM，返回成功发出的个数（忽略单个失败）。"""
    killed = 0
    for pid in pids:
        try:
            subprocess.run(["kill", "-TERM", str(pid)], timeout=5)
            killed += 1
        except (subprocess.SubprocessError, OSError):
            continue
    return killed


def _dev_server_worktree_root(tokens: list) -> Optional[Path]:
    """从 dev-server argv 解析其归属 worktree 根；不携带 worktree 路径返回 None。

    argv 形如 ``[node, dev-server.mjs, <wt>/core/dashboard/static, <port>, ...]``。
    """
    for t in tokens:
        if not t.startswith("/") or "/worktrees/" not in t:
            continue
        prefix, rest = t.split("/worktrees/", 1)
        wt_name = rest.split("/", 1)[0]
        if wt_name:
            return Path(prefix) / "worktrees" / wt_name
    return None


def _worktree_has_live_referencing_process(wt_root: Path, exclude_pid: int) -> bool:
    """进程表中是否存在（除 dev-server 自身外）引用该 worktree 的进程。

    attempt 的 claude 进程经 --add-dir 引用 worktree 目录；dev-server 自身
    cmdline 也含该路径，需排除，否则永远「存活」。
    """
    try:
        res = subprocess.run(
            ["pgrep", "-f", f"worktrees/{wt_root.name}"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    if res.returncode != 0 or not res.stdout.strip():
        return False
    return any(int(s) != exclude_pid for s in res.stdout.split() if s.strip().isdigit())


def _dev_server_orphan_pids() -> list:
    """识别孤儿 dev-server PID：worktree 已消失，或无任何存活进程归属。

    背景（admin 处置 v2-alerts-activities）：孤儿 dev-server 的 argv 残留已删除
    worktree 的路径，被 worktree_manager 的 pgrep 存活探测误判为持锁 attempt
    → spec 锁永不释放 → 派发滞留（dispatch_stalled）。反向缺陷同样要防：
    无差别按标记清理会误杀 daemon 重启时仍在服务的活跃 run dev-server。
    故以「worktree 存在 且 有存活归属进程」为豁免条件，两条都检查。
    """
    out = []
    for pid in _pgrep_dev_servers("dev-server.mjs"):
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            tokens = [a.decode("utf-8", "replace") for a in argv if a]
        except OSError:
            continue
        wt_root = _dev_server_worktree_root(tokens)
        if wt_root is None:
            # 不携带 worktree 路径（异常形态）：仅当无存活引用进程才清
            if not _worktree_has_live_referencing_process(Path("nonexistent"), pid):
                out.append(pid)
            continue
        if wt_root.is_dir() and _worktree_has_live_referencing_process(wt_root, pid):
            continue  # 归属存活 attempt，保留
        out.append(pid)
    return out


def cleanup_orphans(logger=None) -> int:
    """daemon 启动时清扫遗留 dev-server（D2）：无存活归属的 dev-server 进程。

    判定（admin 处置 v2-alerts-activities 加固，取代纯标记匹配）：
    dev-server argv 携带 worktree 路径，据此判断其归属——worktree 已消失、
    或进程表中无该 worktree 的存活归属进程（attempt 已死而 server 残留）→
    孤儿，回收；归属存活 attempt → 保留（daemon 重启可能先于子进程结束）。
    防止残留进程被 worktree_manager 的 pgrep 存活探测误判为持锁 attempt。

    Returns: 被终止的进程数。
    """
    pids = sorted(set(_dev_server_orphan_pids()))
    if not pids:
        return 0
    killed = _kill_pids(pids)
    if killed and logger:
        logger.warning("v2_dev_server", f"cleaned up {killed} orphan dev-server(s)")
    return killed

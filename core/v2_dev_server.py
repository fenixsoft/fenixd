"""
v2_dev_server.py — per-run 隔离测试服务生命周期管理（add-worktree-test-server）。

框架在派发 implementer/verifier 进入 worktree 前，于 worktree 内启动专属测试
服务（dev-server.mjs）：静态资源由 worktree 副本提供，后端 API/SSE 反代至主
服务 8787。端口按确定性策略分配（V2_TEST_PORT_BASE + run序号 mod 区间），冲突
重试；run 终态后框架回收进程。

本模块只负责：端口分配、dev-server.mjs 子进程启停、V2_BASE_URL 注入值计算、
遗留进程清扫（daemon 启动时）。dev-server.mjs 自身实现见 tests/v2/dev-server.mjs。
"""

import json
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.proc_utils import (
    find_free_port,
    guard_killpg,
    is_claude_process,
    pid_alive_stat,
    proc_start_ticks,
)

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

# start 的就绪判定窗口（秒，code-review item 76b1c9ed20c1）：_wait_ready 轮询
# 上限。正常负载下余量充足、不放宽（改超时数值属启动时序调整，非本条目范围）；
# 提为常量供就绪超时错误文案引用同一语义值，便于排障按因识别。
V2_READY_TIMEOUT_SECONDS = 5.0

# 端口抢注（身份不符）有界重试次数（code-review item e2e26c2a1a66）：start()
# 检出端口被抢注后换 run_seq+offset 重新 allocate_port 并重启 dev-server 的
# 最大重试轮数（总尝试 = 1 + 此值）。就绪超时不重试，仍按启动失败上抛。
V2_PORT_CONFLICT_RETRIES = 2

# 不可归因进程记账（fix-v2-devserver-fallback-attribution 2.1）：daemon 进程内
# 状态，重启即失、不持久化——重启后按新进程重放一次首见告警，可接受（重启
# 场景由 reconcile_v2_servers 启动对账兜底）。结构 {pid: 累计扫描见次}：首见
# WARNING 一次，后续静默计数——杜绝同 pid 每个清扫周期（600s）刷一条告警
# （2026-10-02/03 双 daemon 主机同 pid 207 条告警的刷屏形态）。
_unattributed_seen: Dict[int, int] = {}
_unattributed_lock = threading.Lock()


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
    # 归因标记（fix-v2-devserver-fallback-attribution 1.1）：回退形态时置位，
    # 启动时追加到 argv 尾部（见下方回退分支与 cmd 组装处说明）。
    attribution_token: Optional[str] = None
    if not static_root.is_dir():
        # worktree 可能未含 core/dashboard/static：git 不携带构建产物目录，
        # 非框架目标项目（其仓库无 core/dashboard）的 worktree **常态**落此
        # 回退形态；回退主树静态根，保证服务能起，但失去 worktree 隔离意义
        # ——仅作兜底不阻断派发。
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
        # argv 归因标记：回退后 static_root 指向主树（不含 worktree 路径），
        # argv 从此无法被孤儿清扫归因（_dev_server_worktree_root 判 None）→
        # 每 600s 周期性 skip WARNING（2026-10-02/03 potplayer-base 101 条误报
        # 的根因）。此处记下 worktree 侧静态根路径（<wt>/core/dashboard/static，
        # 与 static-root token 同形态），在 cmd 尾部追加，使既有归因/豁免逻辑
        # （_dev_server_worktree_root + _worktree_has_live_referencing_process）
        # 自然生效。
        attribution_token = str(wt_static_root)

    script = _dev_server_script()
    if not script.is_file():
        raise V2DevServerError(f"dev-server.mjs not found: {script}")

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

    # 端口抢注有界重试（code-review item e2e26c2a1a66，模块 docstring「冲突
    # 重试」/design D5 语义落地）：allocate_port 的 bind 探测与 node 实际 bind
    # 之间存在竞窗，端口段 19000-19019 为全主机编译期常量、同主机多 daemon
    # （含不同项目）共用且各 daemon 的 run_seq 从同一初值起算，抢注可现实
    # 发生；检出后原样上抛会使唯一消费方（agent_runner.v2_server）仅 WARNING
    # 即放弃注入、测试回退主树 8787 旧码——正是 D5 明言避免的「旧码污染验证」。
    # 此处换 run_seq+offset 重新 allocate_port 并重启 dev-server（重试只包
    # 「身份不符/port conflict」分支；就绪超时维持启动失败上抛），重试耗尽才
    # 按 V2DevServerError 契约上抛。首试 offset=0 保持既有确定性端口序不变；
    # 每轮失败子进程均按 _kill 既有清理语义回收，不残留。
    for attempt in range(V2_PORT_CONFLICT_RETRIES + 1):
        try:
            # design D5：allocate_port 不再抛 V2DevServerError（耗尽回退临时端口）；
            # 保留防御性捕获，覆盖未来新增异常形态。
            port = allocate_port(run_seq + attempt, used_ports, logger=logger)
        except V2DevServerError as e:
            if logger:
                logger.error("v2_dev_server", f"port allocation failed: {e}")
            raise

        # 把标记字面量写入 argv，使 daemon 重启后 pgrep -f 能按完整命令行识别该子进程
        # （标记不写入 .mjs 源码，避免干扰脚本自身参数解析）。见 cleanup_orphans。
        cmd = [
            _node_bin(),
            str(script),
            str(static_root),
            str(port),
            V2_DEV_SERVER_MARKER,
        ]
        if attribution_token:
            # 回退形态归因标记（fix-v2-devserver-fallback-attribution 1.1）：MUST
            # 追加在**尾部**——dev-server.mjs 按位置读 argv[2]=static_root、
            # argv[3]=port（tests/v2/dev-server.mjs:25-26），前插会改变脚本语义；
            # 标记只供清扫 pgrep/argv 解析消费，node 自身不读它。追加不改变既有
            # pgrep 匹配模式（匹配键仍含 dev-server.mjs 路径与 marker 字面量）。
            cmd.append(attribution_token)

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
            raise V2DevServerError(f"failed to spawn dev-server: {e}") from e

        # 等待端口就绪（dev-server.mjs 监听后即写 "listening"；不读 stdout 时用探测）。
        # 连通成功后还须做实例身份收口：allocate_port 的 bind 探测与 node 实际 bind
        # 之间存在窗口，端口可能被他方进程抢注——node bind 失败（已退出或僵而未死）
        # 时 connect 握手由他方 listener 应答，仅凭连通会误判就绪、把验证流量打到
        # 异码服务上。同一 addr:port 的 LISTEN socket 唯一（node 未用 SO_REUSEPORT），
        # 核对端口 LISTEN inode 是否归属本进程 /proc/<pid>/fd 即可确定性判定应答者
        # 身份，取代「延迟数百毫秒再看存活」的时长启发式（进程存活≠端口归它）。
        ready = _wait_ready(port, timeout=V2_READY_TIMEOUT_SECONDS)
        # 身份收口仅在连通后执行（保持原 and 短路语义：超时路径不再核对端口归属）。
        served_by_self = _port_listened_by(port, proc) if ready else False
        if ready and served_by_self:
            break
        # 失败归因二分（code-review item 76b1c9ed20c1）：就绪超时（高载下 node
        # 冷启动超窗）与端口身份不符（allocate_port bind 探测与 node 实际 bind
        # 之间被抢注 / proc 已退出）是两类现场，错误文案区分开供调用方/排障
        # 按因识别；就绪超时维持既有「回收子进程后按启动失败上抛」语义，身份
        # 不符回收后有界重试（item e2e26c2a1a66，见循环上方说明）。
        if not ready:
            _log(
                "error",
                f"dev-server on port {port} not ready within "
                f"{V2_READY_TIMEOUT_SECONDS:.0f}s, killing",
            )
            _kill(proc)
            raise V2DevServerError(
                f"dev-server on port {port} not ready within "
                f"{V2_READY_TIMEOUT_SECONDS:.0f}s (readiness timeout)"
            )
        # 身份不符（端口被抢注）：回收本轮子进程（_kill 清理语义不变）后换端口
        # 重试；重试耗尽按原错误文案上抛，消费方捕获/降级形态不变。
        _kill(proc)
        if attempt < V2_PORT_CONFLICT_RETRIES:
            _log(
                "warning",
                f"dev-server on port {port} listened by another process, "
                f"retrying with next port "
                f"({attempt + 1}/{V2_PORT_CONFLICT_RETRIES})",
            )
            continue
        _log(
            "error",
            f"dev-server on port {port} ready but port not served by it, killing",
        )
        raise V2DevServerError(
            f"dev-server on port {port} listened by another process (port conflict)"
        )

    if used_ports is not None:
        used_ports.add(port)
    _log("info", f"dev-server started pid={proc.pid} port={port} " f"static={static_root}")
    return port, proc


def _wait_ready(port: int, timeout: float = 5.0) -> bool:
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


def _listen_inode(port: int) -> List[str]:
    """取 port 当前全部 LISTEN socket 的 inode（/proc/net/tcp[6]；无则空表）。

    /proc/net/tcp 固定布局：local_address 形如 0100007F:4A38（IP:十六进制
    端口）、第 4 列 st=0A 即 LISTEN、第 10 列为 socket inode。收集该端口
    全部 LISTEN 条目而非首条：wildcard（00000000/::）与具体地址（如
    0100007F）可被不同进程同时 LISTEN 同一端口，只取首条可能命中他方
    socket 的 inode，导致身份收口误判。
    """
    inodes: List[str] = []
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            rows = Path(table).read_text().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            fields = row.split()
            try:
                if fields[3] == "0A" and int(fields[1].rsplit(":", 1)[1], 16) == port:
                    inodes.append(fields[9])
            except (IndexError, ValueError):
                continue
    return inodes


def _port_listened_by(port: int, proc: subprocess.Popen, timeout: float = 2.0) -> bool:
    """核对 port 上的 LISTEN socket 是否归属 proc（就绪判定的实例身份收口）。

    _wait_ready 只证明「有 listener 应答」；若 allocate_port 的 bind 探测与
    node 实际 bind 之间端口被抢注，应答者是他方进程、验证流量会打到异码服务。
    同一 addr:port 不可能存在两个 LISTEN（node 未用 SO_REUSEPORT），但 wildcard
    与具体地址可被不同进程同时 LISTEN 同一端口，故收集该端口全部 LISTEN
    inode 逐一与 proc 的 /proc/<pid>/fd 比对，任一命中即证明 proc 自身持有
    该端口 LISTEN socket（应答者含本实例），判定与进程退出时机无关。就绪即
    命中通常首轮通过；短暂重试仅覆盖 node 尚在 bind 的窗口与 procfs 目录
    整体不可读（单 fd 瞬时读取失败就地跳过、不弃本轮），proc 已退出（bind
    失败自灭）则立即判负。
    """
    deadline = time.time() + timeout
    while True:
        if proc.poll() is not None:
            return False
        inodes = _listen_inode(port)
        if inodes:
            targets = {f"socket:[{inode}]" for inode in inodes}
            try:
                for fd in Path(f"/proc/{proc.pid}/fd").iterdir():
                    # 单个 fd 可能在遍历间隙被对端关闭（readlink 落 ENOENT，
                    # 代理 SSE 的连接 fd 高频生灭）：跳过该 fd 继续扫余项，
                    # 不连带丢弃本轮已扫到的 LISTEN socket；仅 procfs 目录
                    # 整体不可读才整轮放弃、交由重试窗兜底。
                    try:
                        link = os.readlink(fd)
                    except OSError:
                        continue
                    if link in targets:
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
        # 击杀最后一跳经自保护守卫（add-killpg-self-guard）：pgid 已解析直传；
        # 守卫拒绝（自身组/非正 pgid）与组已不存在同样静默，序列语义不变。
        guard_killpg(pgid, signal.SIGTERM, caller="v2_dev_server._kill", resolve=False)
        try:
            proc.wait(timeout=5)
            # 组长虽按时退出，组内仍可能有忽略 SIGTERM 的组员（shell/npm 包装
            # 链形态），返回前对进程组补一次 SIGKILL 收尾，确保「杀整棵树」
            # 成立；组已空（全员随 SIGTERM 退出）按已清算静默处理（守卫对
            # ESRCH/自身组/非正 pgid 返回 False 不抛）。
            guard_killpg(pgid, signal.SIGKILL, caller="v2_dev_server._kill", resolve=False)
            return
        except subprocess.TimeoutExpired:
            pass
        except OSError:
            pass
    # 2) 进程组 SIGKILL → 等待退出（宽限期后仍无响应的残留强制终止）
    if pgid is not None:
        guard_killpg(pgid, signal.SIGKILL, caller="v2_dev_server._kill", resolve=False)
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
            # SIGKILL 命中后收尾 wait()：否则子进程残留僵尸态，直至下一次
            # spawn 才被 subprocess 的 _active 机制顺带回收。
            try:
                proc.wait(timeout=1)
            except (subprocess.TimeoutExpired, OSError):
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
    # [fenix-ignore:e2a83fea7d79] 有意不加防护/可观测：pgrep -f 匹配 marker 字面量的
    # 命中数受 dev-server 实际数量约束（个位数），无超大输出风险；pgrep 缺失
    # 被吞为空列表与 docstring 声明的降级口径一致（清扫能力静默退化），不值得
    # 为其新增按进程生命周期去重的告警面（code-review e2a83fea7d79 判 not_worth_fixing）
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

    /proc stat 解析与判定上移 core.proc_utils 单点（consistency：三处探针
    助手收敛），zombie_is_dead=True 显式选择本模块的 Z=死口径。
    """
    return pid_alive_stat(pid, zombie_is_dead=True)


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


def _pid_cwd(pid: int) -> Optional[Path]:
    """读取 /proc/<pid>/cwd 符号链接目标（读取失败/进程已消亡返回 None）。"""
    try:
        return Path(os.readlink(f"/proc/{pid}/cwd"))
    except OSError:
        return None


def _kill_pids(pids: list, logger=None) -> int:
    """对 PID 列表逐个 SIGTERM，短暂轮询 /proc 确认退出，仍存活补 SIGKILL。

    与 _kill 同走信号直发、不经外部 kill 二进制（其缺失会使清扫静默退化
    为空操作）；同守 D2 进程组杀树纪律——pgrep 命中的可能是 shell/npm 包装
    链形态的组长，单 pid 直发杀掉包装 shell 后 node 孙进程仍存活，故先取
    pgid 按组发信号整树终止，取组失败（恰已亡/权限不足）退回单 pid 直发。
    返回确认已终止的进程数（单个 pid 操作失败——权限
    不足/竞态消失——按未终止计，忽略继续）。等待有界：SIGTERM 后至多 ~2s、
    SIGKILL 后至多 ~1s，不阻塞调用方（启动清扫/周期清扫均可容忍秒级）。
    """
    killed = 0
    for pid in pids:
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            continue  # 恰已退出（竞态），按未终止计
        except (PermissionError, OSError):
            pgid = None  # 取组失败：退回单 pid 直发（同 _kill 兜底口径）
        try:
            if pgid is not None:
                # 自保护守卫（add-killpg-self-guard）：拒绝（自身组/非正 pgid）
                # 与组已不存在同样按竞态消失计，不得降级单 pid 直发（os.kill(0)
                # 经折算同为调用者自身组广播）。
                if not guard_killpg(
                    pgid, signal.SIGTERM, caller="v2_dev_server._kill_pids", resolve=False
                ):
                    continue
            else:
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
                if pgid is not None:
                    if not guard_killpg(
                        pgid, signal.SIGKILL, caller="v2_dev_server._kill_pids", resolve=False
                    ):
                        continue
                else:
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass  # 竞态消失/权限不足，交由末尾 _pid_alive 判定
            for _ in range(10):  # ~1s 上限等待 SIGKILL 生效
                if not _pid_alive(pid):
                    break
                time.sleep(0.1)
        # 组级 SIGKILL 收尾（与 _kill 的收尾口径对称，0b5d32a67584）：组长
        # （受检 pid）消亡≠组清算完毕——忽略 SIGTERM 的组员（node 卡死的
        # 孙进程形态）会残留为孤儿，无条件对已解析 pgid 补一次 SIGKILL；
        # 组已空（全员随 SIGTERM 退出）按已清算静默处理（守卫对 ESRCH/
        # 自身组/非正 pgid 返回 False 不抛）。pgid 解析失败的单 pid 直发
        # 路径无组可补。
        if pgid is not None:
            guard_killpg(
                pgid, signal.SIGKILL, caller="v2_dev_server._kill_pids", resolve=False
            )
        if not _pid_alive(pid):
            killed += 1
    return killed


def _dev_server_worktree_root(tokens: list) -> Optional[Path]:
    """从 dev-server argv 解析其归属 worktree 根；不携带 worktree 路径返回 None。

    argv 形如 ``[node, dev-server.mjs, <wt>/core/dashboard/static, <port>, ...]``。
    以静态根 token（含 ``/core/dashboard/static`` 尾缀）为**权威归属**：脚本自身
    路径在框架运行于 worktree 内时（本仓库以 worktree 为开发态时）同样含
    ``/worktrees/``，若按首个命中会误把脚本路径解析为归属 worktree。

    取**末个**命中而非首个（fix-v2-devserver-fallback-attribution 1.1）：回退
    形态会在 argv 尾部追加归属标记 token（<wt>/core/dashboard/static）；框架
    自身运行于 worktree（开发态）时，回退用的主树静态根 token 同样含
    /worktrees/ 且位置在前——归属语义必须让位于显式追加的标记 token（它承载
    run 的真实归属 worktree，而非被服务静态内容的来源）。常态形态只有静态根
    一个命中 token，末个==首个，行为不变；token 内多段 /worktrees/ 仍按
    rsplit 末段归属（下方注释，回归守卫不变）。
    """
    found = None
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
            found = Path(prefix) / "worktrees" / wt_name
    return found


def _worktree_has_live_referencing_process(wt_root: Path, exclude_pid: int) -> bool:
    """进程表中是否存在（除 dev-server 自身外）引用该 worktree 的**存活进程**。

    argv 维度：attempt 的 claude 进程经 --add-dir 引用 worktree 目录，cmdline
    携带路径 token；dev-server 自身 cmdline 也含该路径，需排除，否则永远
    「存活」。

    cwd 维度（code-review item 9cf345f60aee）：dsh 通道 agent 的 argv 仅含
    dsh/--profile/--patch/--json，worktree 只落在 cwd、cmdline 不含路径
    token，argv 维度探测结构性落空——在服 run 的 dev-server 会被误判孤儿
    遭周期清扫/reconcile 击杀（V2_BASE_URL 悬挂）。故补 /proc/<pid>/cwd ==
    wt_root 判定，使豁免判据与 harness 的 argv 形态解耦（claude 经
    --add-dir、dsh 经 cwd，形态随 harness 漂移，argv 识别名集合不可依赖）。

    design D4（豁免过滤修复）：argv 维度的有效豁免**必须**以 agent 可执行名
    为锚——否则同一 worktree 的两个孤儿 dev-server 互为"存活引用"互相豁免、
    永不清扫（09-04/05 事故根因之一）。cwd 维度无此隐患：dev-server 的 cwd
    继承 daemon（项目根）而非 worktree，同 wt 孤儿互不构成 cwd 引用，D4
    防线仍成立；与 worktree_manager._worktree_has_live_process 的 argv 维度
    同判定。
    """
    # 尾边界防串扰：pgrep -f 按子串 ERE 匹配，worktree 名 foo 会连引用
    # worktrees/foo-bar 的进程一并命中（跨 worktree 误豁免）；须后随
    # /、空白或行尾才算引用本 worktree。名含正则元字符时 re.escape
    # 免被当作模式语法解释。pgrep 调用与解析复用 _pgrep_dev_servers
    # （pgrep 不可用/超时/无命中返回空列表 → any 恒 False，与原内联
    # 实现的错误语义等价）。
    # [fenix-ignore:d60a0053fec3] 裸 name 匹配系有意取舍：全路径收窄（re.escape(str(wt_root))）与豁免替身的裸 token 契约冲突，且引用 argv 路径形态漂移时豁免落空＝误杀在服 run，代价高于本条 info 级漏清（ppid 自灭兜底仍在）。
    pids = _pgrep_dev_servers(
        rf"worktrees/{re.escape(wt_root.name)}(/|[[:space:]]|$)"
    )
    if any(
        pid != exclude_pid and is_claude_process(str(pid)) for pid in pids
    ):
        return True
    # cwd 维度扫描（harness 无关）：cwd 直接落在该 worktree 的存活进程即归属
    # 引用，不再锚可执行名。方向性取舍：旁观进程（人工 shell 停在 wt 内）
    # 命中造成的是漏清一轮，远低于误杀在服 run（V2_BASE_URL 悬挂、验证伪
    # 失败）；僵尸态按已亡不计（_pid_alive 口径）。realpath 兜底：argv token
    # 可经未解析软链（tmp 软链等），内核 cwd 恒为解析后路径，直接相等失配
    # 时按归一路径再比对一次，防维度结构性落空。
    wt_real = os.path.realpath(wt_root)
    try:
        proc_ids = os.listdir("/proc")
    except OSError:
        return False
    for name in proc_ids:
        if not name.isdigit():
            continue
        pid = int(name)
        if pid == exclude_pid or not _pid_alive(pid):
            continue
        cwd = _pid_cwd(pid)
        if cwd is not None and (
            cwd == wt_root or os.path.realpath(cwd) == wt_real
        ):
            return True
    return False


def _argv_touches_worktree_base(tokens: list, worktree_base: Path) -> bool:
    """argv 是否携带本项目 worktree 基路径的绝对路径 token（项目收窄判据）。

    整路径前缀匹配（非裸子串，避免同主机相似路径误命中）：正常形态
    dev-server 的 static-root token 与回退形态追加的归因标记 token 均携带
    ``<worktree_base>/`` 前缀；两者皆无（旧版回退形态存量进程/他项目进程）
    则不属本项目裁量范围。
    """
    prefix = str(worktree_base).rstrip("/") + "/"
    return any(t.startswith(prefix) for t in tokens if t.startswith("/"))


def _is_dev_server_argv(tokens: list) -> bool:
    """argv 是否为本框架 node 起停形态（marker 裸子串命中的旁观进程过滤）。

    dev-server 由本模块以 ``node <dev-server.mjs> ...`` 起停；pgrep -f 按
    marker 裸子串匹配全系统 cmdline，排障类命令（grep/tail 的参数同时含
    marker 字面量与 worktree 静态根路径）会被收进候选，若放行会被归因/
    归属判定收进孤儿分类遭误杀。argv[0] 非 node、或 node 后既非脚本路径也
    非选项的命中不是本框架起停的 dev-server，直接排除：
    - 常态/回退形态 ``[node, <script>, <static_root>, <port>, marker, ...]``：
      argv[1] 即脚本路径（脚本路径只比对文件名，跨 worktree 形态同样命中）；
    - node 选项形态（-c/--inspect 等）：argv[1] 以 ``-`` 开头。
    """
    if len(tokens) < 2 or Path(tokens[0]).name != "node":
        return False
    second = tokens[1]
    return second.startswith("-") or Path(second).name == _dev_server_script().name


def _dev_server_orphan_pids(logger=None, worktree_base=None) -> list:
    """识别孤儿 dev-server PID：worktree 已消失，或无任何存活进程归属。

    背景（admin 处置 v2-alerts-activities）：孤儿 dev-server 的 argv 残留已删除
    worktree 的路径，被 worktree_manager 的 pgrep 存活探测误判为持锁 attempt
    → spec 锁永不释放 → 派发滞留（dispatch_stalled）。反向缺陷同样要防：
    无差别按标记清理会误杀 daemon 重启时仍在服务的活跃 run dev-server。
    故以「worktree 存在 且 有存活归属进程」为豁免条件，两条都检查。
    另设启动宽限豁免：启动不足 60s 的 dev-server 本轮一律跳过（派发先启
    dev-server、再 spawn claude 的秒级窗口内归属探测必然落空，防周期清扫
    TOCTOU 误杀在服 run）。

    fix-v2-devserver-fallback-attribution：worktree_base 传入时扫描面按项目
    收窄（2.1）——argv 不携带本项目 worktree 基路径的进程不记账不告警不清扫
    （双 daemon 主机各管各的，不互刷）；不可归因进程（旧版回退形态存量）按
    pid 记账，首见告警一次、后续静默计数（2.1），处置以「无引用进程」为前提
    （2.2 文案联动），不按裸存活时长自动 kill。
    """
    out = []
    seen_unattributed = set()
    for pid in _pgrep_dev_servers(V2_DEV_SERVER_MARKER):
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            tokens = [a.decode("utf-8", "replace") for a in argv if a]
        except OSError:
            continue
        if not _is_dev_server_argv(tokens):
            # marker 裸子串 pgrep 会命中 cmdline 恰携带 marker 字面量与
            # worktree 静态根路径的旁观进程（code-review item 0eb953af2d11，
            # 排障类 grep/tail 参数形态）：非 node 起停形态不是本框架的
            # dev-server，不记账不告警不清扫——放行会被下方归因/归属判定
            # 收进孤儿分类，cleanup_orphans 对无关进程组发 SIGTERM/SIGKILL。
            continue
        if worktree_base is not None and not _argv_touches_worktree_base(
            tokens, Path(worktree_base)
        ):
            # 扫描面按项目收窄（fix-v2-devserver-fallback-attribution 2.1）：
            # pgrep -f 全局匹配会命中同主机其他项目 daemon 的 dev-server，同
            # pid 在两份日志各刷一条（2026-10-02/03 双 daemon 207 条告警）。
            # 他项目进程不记账、不告警、不清扫——归属与豁免判据（worktree
            # 基路径、存活 claude 引用）本就以本项目为界，越界判定无意义。
            continue
        wt_root = _dev_server_worktree_root(tokens)
        if wt_root is None:
            # 不携带 worktree 路径（旧版主树静态根回退形态存量进程）：argv 无
            # 归属可探测，按虚构路径反查 pgrep 恒落空（恒判孤儿、误杀在服 run）。
            # 归属 attempt 的 claude 进程经 --add-dir 引用 worktree 路径，无法从
            # argv 反推，故无安全探测面——保守跳过清扫，按 pid 记账（2.1）：
            # 首见告警一次、后续静默计数（该形态对非框架目标项目的存量进程
            # 是常态，且 dev-server 仍有 ppid 绑定自灭兜底）。处置前提：确认
            # 无存活进程引用其来源 worktree 后方可人工处置——禁止按裸存活
            # 时长自动 kill，在服 run 可合法长持（实测 4.2h），误杀会打断
            # 验证（V2_BASE_URL 悬挂）。
            with _unattributed_lock:
                first_seen = pid not in _unattributed_seen
                _unattributed_seen[pid] = _unattributed_seen.get(pid, 0) + 1
            seen_unattributed.add(pid)
            if logger and first_seen:
                static_root = next(
                    (t for t in tokens if "/core/dashboard/static" in t), "")
                logger.warning(
                    "v2_dev_server",
                    f"orphan sweep skipped for pid={pid}: argv carries no "
                    f"worktree path (static_root={static_root or 'unknown'}) "
                    f"— 不可归因残留 dev-server（主树静态根回退形态存量），"
                    f"归属无法安全判定：在服 run 可合法长持，误杀会打断验证"
                    f"（V2_BASE_URL 悬挂）。已按 pid 记账，本告警首见一次、"
                    f"后续静默计数；仅当确认无存活进程引用其来源 worktree 后"
                    f"方可人工处置，勿按存活时长直接 kill",
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
    # 记账簿瘦身：本轮未见且已消亡的 pid 移除（防 dict 随历史 pid 无界增长，
    # 也让 pid 复用后能重放首见告警）；仍存活但本轮 pgrep 未命中的保留计数，
    # 避免瞬时 pgrep 抖动重放首见告警。
    with _unattributed_lock:
        for stale in [
            p for p in _unattributed_seen
            if p not in seen_unattributed and not _pid_alive(p)
        ]:
            _unattributed_seen.pop(stale, None)
    return out


def cleanup_orphans(logger=None, worktree_base=None) -> int:
    """daemon 启动与周期清扫共用的孤儿回收入口（D2）：无存活归属的 dev-server 进程。

    调用方两处：fenixd.py 启动序列与每 600s 周期清扫（verify-process-lifecycle
    D4，孤儿泄漏可见窗口 ≤ 一个周期）；启动宽限豁免正是为周期清扫的
    TOCTOU 窗口设计。

    判定（admin 处置 v2-alerts-activities 加固，取代纯标记匹配）：
    dev-server argv 携带 worktree 路径，据此判断其归属——worktree 已消失、
    或进程表中无该 worktree 的存活归属进程（attempt 已死而 server 残留）→
    孤儿，回收；归属存活 attempt → 保留（daemon 重启可能先于子进程结束）。
    防止残留进程被 worktree_manager 的 pgrep 存活探测误判为持锁 attempt。
    argv 不携带 worktree 路径（主树静态根回退形态存量）→ 无归属可探测，保守
    跳过并按 pid 记账留痕（首见 WARNING 一次、后续静默计数，fix-v2-devserver-
    fallback-attribution 2.1/2.2；误杀在服 run 比漏清罕见残留代价更高）。

    Args:
        worktree_base: 本项目 worktree 基目录（2.1 项目收窄判据）。传入时仅
            考量 argv 携带该基路径的 dev-server，同主机多 daemon（多项目）
            互不记账互不清扫；None 保持全局扫描（既有调用/测试形态兼容）。

    Returns: 被终止的进程数。
    """
    pids = sorted(
        set(_dev_server_orphan_pids(logger=logger, worktree_base=worktree_base))
    )
    if not pids:
        return 0
    killed = _kill_pids(pids, logger=logger)
    if killed and logger:
        logger.warning("v2_dev_server", f"cleaned up {killed} orphan dev-server(s)")
    return killed


# ── 在册登记持久化与重启对账（fix-v2-devserver-fallback-attribution 2.3）──────
# _v2_servers 是 daemon 进程内状态（core/agent_runner/v2_server.py:37-48），daemon
# 重启后归零：重启窗口内仍在服的 dev-server 归属从此无人能判定（泄漏盲区，
# 端口池被永久占用）。登记制让启动对账按「pid 存活 + 身份核对 + 归属引用
# 判定」只收割无主进程（形态参照 core/serving_registry.py:351-394 sweep）。
# 登记制是兜底增强而非唯一防线：dev-server 仍有 marker pgrep 扫描路径
# （cleanup_orphans）与 ppid 绑定自灭；json 写入失败仅损失对账覆盖，不制造
# 新失败。文件属运行时状态（.fenix/ 不入库，非仓库交付物）。单写者：文件按
# 项目根隔离，每项目仅一个 daemon 写（原子写 last-writer-wins，并发窗口最坏
# 丢条目＝损失对账覆盖，不损坏文件），进程内以 _registry_io_lock 串行化
# 读改写即可，无需跨进程 fcntl。
V2_SERVERS_FILENAME = "v2_servers.json"

_registry_io_lock = threading.Lock()


def v2_servers_registry_path(project_root) -> Path:
    """登记文件绝对路径：<project_root>/.fenix/v2-serving/v2_servers.json。"""
    return Path(project_root) / ".fenix" / "v2-serving" / V2_SERVERS_FILENAME


def _registry_pid_valid(pid) -> bool:
    """登记 pid 形状校验：真整型（显式排除 bool）且 >0。

    bool 是 int 子类：手改 v2_servers.json 写入的 ``{"pid": true}`` 在纯
    isinstance/>0 检查下会被当作 pid=1 走判活路径（True > 0，os.kill(1, 0)
    探的是 pid 1）——对齐 serving_registry.sweep 的显式加固口径。
    """
    return isinstance(pid, int) and not isinstance(pid, bool) and pid > 0


def _registry_pid_eq(stored, pid) -> bool:
    """登记 pid 严格比对：双侧都须为真整型才允许值比较。

    纯 ``==`` 下 True == 1 与整型 pid=1 互相匹配（register 幂等误命中），
    形态同 serving_registry._pid_eq。
    """
    return (
        _registry_pid_valid(stored)
        and _registry_pid_valid(pid)
        and stored == pid
    )


def load_v2_server_entries(project_root, logger=None) -> list:
    """读登记条目（文件缺失/损坏返回空；非 dict 条目剔除）。

    文件缺失（从未登记）与内容损坏同返回空，但对账语义不同：损坏＝重启前
    在册条目的收割线索丢失（对账覆盖缺口），传 logger 时输出 WARNING 留痕
    （e0a3a75d196f，不传保持静默、既有调用形态兼容）；下次 register 重写
    文件自愈。
    """
    path = v2_servers_registry_path(project_root)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []  # 缺失/不可读：非损坏，无需留痕
    except UnicodeDecodeError as exc:
        # 坏字节与非法 JSON 同口径（UnicodeDecodeError 是 ValueError 子类、
        # 非 OSError，不接住会打断「下次 register 重写自愈」闭环，形态同
        # serving_registry._read_unlocked）：WARNING 留痕后返回空列表。
        if logger:
            logger.warning(
                "v2_dev_server",
                f"v2 server registry file corrupt (invalid UTF-8: {exc}), "
                f"treating as empty: {path} — 重启前在册条目线索丢失，"
                f"对账覆盖缺口留痕（下次 register 重写自愈）",
            )
        return []
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if not isinstance(data, list):
        if logger:
            logger.warning(
                "v2_dev_server",
                f"v2 server registry file corrupt (invalid JSON/list), "
                f"treating as empty: {path} — 重启前在册条目线索丢失，"
                f"对账覆盖缺口留痕（下次 register 重写自愈）",
            )
        return []
    return [e for e in data if isinstance(e, dict)]


def _rewrite_v2_server_entries(project_root, entries: list) -> bool:
    """原子重写登记文件（临时文件 + replace）。OSError 返回 False 不抛。"""
    path = v2_servers_registry_path(project_root)
    tmp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".v2_servers.", suffix=".tmp", dir=str(path.parent)
        )
        tmp_path = Path(tmp_name)
        f = None
        try:
            f = os.fdopen(fd, "w", encoding="utf-8")
            with f:
                json.dump(entries, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
        finally:
            # fdopen 自身抛错时 with 未绑定文件、裸 fd 无人关闭——daemon
            # 长生命周期内描述符泄漏，兜底 os.close（对齐
            # write_narrative_sidecar / regression._atomic_write 口径）。
            if f is None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        os.replace(str(tmp_path), str(path))
        tmp_path = None
        return True
    except OSError:
        return False
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def register_v2_server(project_root, wt_path, pid: int, port: int, logger=None) -> None:
    """登记一条在册 dev-server（launch 成功时调用，best-effort 不阻断派发）。

    带 /proc starttime 快照：pid + starttime 唯一确定进程实例，重启对账据此
    做 pid 复用防误杀（纪律同 serving_registry._harvest_identity_ok）。同
    (wt_path, pid) 已登记时幂等刷新快照；追加新条目前顺带剔除同 wt_path 下
    pid 已消亡的陈旧条目（bf367d5f331c，防异常重启轮次在 daemon 生命周期内
    线性累积滞留）。写失败仅 WARNING（调用方 logger 可为 None 时静默）。
    """

    def _upsert(entries: list) -> None:
        for e in entries:
            if _registry_pid_eq(e.get("pid"), pid) and e.get("wt_path") == str(wt_path):
                e["port"] = port
                e["start_ticks"] = proc_start_ticks(pid)
                e["registered_at"] = int(time.time())
                return
        # 条目瘦身（code-review item bf367d5f331c）：追加新条目前剔除同 wt_path
        # 下 pid 已消亡的陈旧条目——dev-server 崩溃/异常后同 worktree 换 pid 重新
        # launch 时，旧条目只能滞留到 daemon 重启 reconcile_v2_servers 才按 pid
        # 消亡摘除（周期清扫不触登记面），长生命周期 daemon 内登记随异常重启
        # 次数线性增长；对齐 _unattributed_seen 的记账瘦身纪律。只摘死条：存活
        # 条目与形态非法条目（pid 形状不合法，身份无从判定，交由 reconcile 既有
        # 分支处置）一律不动，防误删在服登记；判活口径与 reconcile 的消亡分支
        # 一致（_pid_alive，Z 态视同已终止）。
        entries[:] = [
            e
            for e in entries
            if not (
                e.get("wt_path") == str(wt_path)
                and _registry_pid_valid(e.get("pid"))
                and not _pid_alive(e["pid"])
            )
        ]
        entries.append(
            {
                "wt_path": str(wt_path),
                "pid": pid,
                "port": port,
                "start_ticks": proc_start_ticks(pid),
                "registered_at": int(time.time()),
            }
        )

    with _registry_io_lock:
        entries = load_v2_server_entries(project_root)
        _upsert(entries)
        if not _rewrite_v2_server_entries(project_root, entries) and logger:
            logger.warning(
                "v2_dev_server",
                f"v2 server registry write failed (non-blocking): "
                f"{v2_servers_registry_path(project_root)}",
            )


def unregister_v2_server(project_root, wt_path, pid=None, logger=None) -> None:
    """移除登记（终态回收时调用，best-effort）。

    pid 传入时按 (wt_path, pid) 精确匹配；未传按 wt_path 匹配全部条目。
    """
    with _registry_io_lock:
        entries = load_v2_server_entries(project_root)
        kept = [
            e for e in entries
            if not (
                e.get("wt_path") == str(wt_path)
                and (pid is None or _registry_pid_eq(e.get("pid"), pid))
            )
        ]
        if len(kept) != len(entries):
            if not _rewrite_v2_server_entries(project_root, kept) and logger:
                logger.warning(
                    "v2_dev_server",
                    f"v2 server registry write failed (non-blocking): "
                    f"{v2_servers_registry_path(project_root)}",
                )


def reconcile_v2_servers(project_root, logger=None) -> int:
    """daemon 启动对账：按登记收割无主 dev-server（2.3），返回收割数。

    daemon 重启后 _v2_servers 进程内状态归零，登记文件是重启前在册实例的
    唯一线索。逐条判定（「记账 + 身份核对 + 收割」形态参照
    core/serving_registry.py:351-394）：

    - pid 已消亡 → 仅摘登记（自然消亡/自灭，无进程可收割）；
    - pid 存活但 starttime 快照失配 → 先复查判活（a9776777a028）：判活与
      starttime 读取窗口内进程恰好退出属竞态消失，静默摘登记；复查仍存活
      才是 pid 已被复用，告警留痕后仅摘登记**不杀**（误杀无关进程的代价
      远高于漏清，同 serving_registry 身份核对纪律）；
    - pid 存活但快照缺失/非法（如 register 时 proc 刚 spawn 即死，
      proc_start_ticks 返回 None）→ 身份无法核实，仅摘登记**不杀**（同上
      纪律，防 pid 复用后误杀无关进程）；
    - pid 存活且身份匹配 → 按登记 wt_path 判归属引用：worktree 已消失、或
      无存活引用进程 → 无主，收割进程并摘登记；有存活引用进程 → 在服 run
      跨重启存活，保留进程与登记（归因标记形态另受周期清扫 argv 判据保护，
      终态回收后条目由下次对账按 pid 消亡摘除）。

    锁分段（2e23776e7c27）：持锁段只做登记读与摘登记回写（文件 I/O），
    身份/归属判定与 _kill_pids 均在锁外执行——单 pid 击杀最长约 3s
    （SIGTERM 等 2s + SIGKILL 等 1s）、pgrep 归属探测每次至多 5s，多无主
    条目时持锁时间线性放大并阻塞派发/终态回收路径的 register/unregister。
    回写以重读登记为基线仅剔除已判定摘除的条目键，锁外窗口内并发 register
    落入的新条目不丢；键命中另按 start_ticks/registered_at 锚点复核（范式同
    serving_registry.sweep._purge），防击杀窗口内 pid 复用后同键新登记被
    stale 名单连带误删。

    与 cleanup_orphans 互补：本函数覆盖「argv 不可归因但登记在册」的存量
    回退形态进程——登记 wt_path 补上了 argv 缺失的归属线索。启动宽限豁免
    （<60s）同样适用：引用进程可能在 dev-server 落地后才 spawn（TOCTOU 防
    误杀，同 _dev_server_orphan_pids）。
    """
    killed = 0
    with _registry_io_lock:
        entries = load_v2_server_entries(project_root, logger=logger)
    if not entries:
        return 0
    # 身份/归属判定在锁外执行（锁分段，2e23776e7c27）：只读 /proc 与 pgrep
    # 探测，不触登记文件，无需占锁。
    kept = []
    harvest = []
    for entry in entries:
        pid = entry.get("pid")
        wt_text = str(entry.get("wt_path") or "")
        if not _registry_pid_valid(pid):
            continue  # 形状非法条目（含 bool 形态）：丢弃
        if not _pid_alive(pid):
            continue  # 已消亡：摘登记
        snapshot = entry.get("start_ticks")
        # bool 显式排除（code-review 6c9a404d284f）：bool 是 int 子类，手改
        # v2_servers.json 写 true 会以 True>0 通过纯 isinstance/>0 形状检查，
        # 随后恒与真实 start_ticks 失配被误判 pid 复用——复用 _registry_pid_valid
        # 与 pid 校验口径对齐（命中走下方「快照缺失/非法」摘登记不杀分支）。
        if not _registry_pid_valid(snapshot):
            # 快照缺失/非法：身份无法核实（eecd5c191ad7），与 pid 复用同
            # 语义——摘登记不杀，防 pid 被复用后误杀无关进程。
            if logger:
                logger.warning(
                    "v2_dev_server",
                    f"reconcile skip pid={pid} (wt={wt_text or '-'}) "
                    f"start_ticks snapshot missing — identity "
                    f"unverifiable; removed registry entry without "
                    f"killing",
                )
            continue  # 身份无法核实：摘登记不杀
        if proc_start_ticks(pid) != snapshot:
            # 竞态复查（a9776777a028）：判活（上方 _pid_alive）与 starttime
            # 读取之间的窗口内进程恰好退出时读取返回 None（与快照失配），
            # 真实根因是进程消失而非 pid 复用——复查已消亡则静默摘登记
            # （与上方已消亡分支同口径），仅复查仍存活才报 pid reused，
            # 避免告警文案把按指纹排障的方向带偏。
            if _pid_alive(pid) and logger:
                logger.warning(
                    "v2_dev_server",
                    f"reconcile skip pid={pid} (wt={wt_text or '-'}) "
                    f"start_ticks mismatch — pid likely reused; removed "
                    f"registry entry without killing",
                )
            continue  # pid 复用/竞态消失：摘登记不杀
        wt_root = Path(wt_text) if wt_text else None
        owned = (
            wt_root is not None
            and wt_root.is_dir()
            and _worktree_has_live_referencing_process(wt_root, pid)
        )
        if owned or _pid_recently_started(pid):
            # 有主（在服 run 跨重启存活）或启动宽限窗内：保留进程与登记
            kept.append(entry)
            continue
        # 无主：worktree 已消失 / 无引用进程 / 登记无 wt_path → 待收割（在
        # 锁外执行）。杀失败（权限/竞态）也摘登记：保留条目只会每轮重试
        # 同一失败，摘除后交由周期清扫的 argv 判据兜底。
        harvest.append((pid, wt_text))
    # 击杀在锁外执行（锁分段，2e23776e7c27）：单 pid 最长约 3s，不占
    # register/unregister 的登记临界区；逐条收割保留单 pid 告警语义。
    for pid, wt_text in harvest:
        if _kill_pids([pid], logger=logger) >= 1:
            killed += 1
            if logger:
                logger.warning(
                    "v2_dev_server",
                    f"reconcile harvested unowned dev-server pid={pid} "
                    f"(wt={wt_text or '-'}) — left unowned across daemon "
                    f"restart",
                )
        elif logger:
            # 击杀失败仍摘登记（交由周期清扫 argv 判据兜底）：补一条告警
            # 留痕，便于排障时识别「登记已摘但进程仍在」的形态。
            logger.warning(
                "v2_dev_server",
                f"reconcile kill failed for unowned dev-server pid={pid} "
                f"(wt={wt_text or '-'}) — registry entry removed; process "
                f"may linger until periodic sweep",
            )
    # 摘登记回写（重新持锁）：以重读登记为基线仅剔除已判定摘除的条目键，
    # 不整表覆写判定时快照——击杀窗口内并发 register 落入的新条目不丢
    # （last-writer-wins 下整表覆写会吞并发登记）。pid 分量取 repr：畸形
    # 条目的 pid 可能是 dict/list 等不可哈希值，repr 恒可哈希且 int/str
    # 形态不混同。键命中另须锚点复核（范式同 serving_registry.sweep._purge）：
    # 随键携带判定时 start_ticks/registered_at 快照——击杀窗口（单 pid 最长
    # 约 3s）内旧 pid 被系统复用且同 worktree 重新 launch 时，register 会以
    # 同 (wt_path, pid) 幂等键就地刷新该条目身份快照，仅按键剔除会把新登记
    # 一并误删、使新实例脱离登记制收割面；fresh 条目锚点仍等于快照才摘，
    # 已刷新（同键新登记）则保留。
    removed_anchors = {
        (str(e.get("wt_path") or ""), repr(e.get("pid"))): {
            "start_ticks": e.get("start_ticks"),
            "registered_at": e.get("registered_at"),
        }
        for e in entries
    }
    for e in kept:
        removed_anchors.pop(
            (str(e.get("wt_path") or ""), repr(e.get("pid"))), None
        )
    # 锚点已刷新而保留的条目：键在锁内比对，留痕统一放锁外（持锁窗口不含
    # 日志，同 serving_registry.sweep 范式）
    anchor_kept = []
    with _registry_io_lock:
        fresh = load_v2_server_entries(project_root)
        merged = []
        for e in fresh:
            anchor = removed_anchors.get(
                (str(e.get("wt_path") or ""), repr(e.get("pid")))
            )
            if anchor is None:
                merged.append(e)  # 非本次判定摘除（含并发新登记）：保留
                continue
            if all(
                e.get(f) == anchor.get(f)
                for f in ("start_ticks", "registered_at")
            ):
                continue  # 锚点未变：即判定时快照所指条目，按判定摘除
            merged.append(e)  # 锚点已刷新：pid 复用后同键新登记，保留
            anchor_kept.append(e)
        if len(merged) != len(fresh):
            if not _rewrite_v2_server_entries(project_root, merged) and logger:
                logger.warning(
                    "v2_dev_server",
                    f"v2 server registry write failed (non-blocking): "
                    f"{v2_servers_registry_path(project_root)}",
                )
    for e in anchor_kept:
        if logger:
            logger.warning(
                "v2_dev_server",
                f"reconcile skip removal pid={e.get('pid')} "
                f"(wt={str(e.get('wt_path') or '-')}) entry anchor "
                f"refreshed since reconcile snapshot (pid reused by new "
                f"register?) — keeping refreshed entry",
            )
    if killed and logger:
        logger.warning(
            "v2_dev_server",
            f"v2 server reconcile harvested {killed} unowned dev-server(s)",
        )
    return killed

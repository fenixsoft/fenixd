"""
server.py — Fenix Web Dashboard 服务器（dashboard-server）。

- 基于 Python 标准库 http.server.ThreadingHTTPServer，零新增依赖（D2）。
- 仅绑定 127.0.0.1，默认端口 8787；被占用时由 serve() 执行端口接管语义
  （dashboard-instance-lifecycle）：旧 dashboard --serve 实例自动终止接管，
  非 dashboard 进程占用则报错退出，绝不静默僵挂。
- REST JSON API + 截图等静态资源服务。
- 所有 API 容错：数据源损坏以字段标记返回，不 500。

端点：
    GET /                          → v3 dashboard 首页
    GET /api/projects              → 监控项目列表 + 各自聚合摘要
    GET /api/overview              → 跨项目状态统计 / 任务进度 / 问题 / 活跃运行
    GET /api/specs?project=<name>  → 某项目全部 SPEC 摘要
    GET /api/specs/<spec>?project=<name> → 单个 SPEC 完整详情
    GET /api/runs/<run_id>?project=<name> → 单次运行产物流
    GET /api/events?project=<name>&minutes=N → 最近 N 分钟结构化事件
    GET /api/spec-doc?project=<name>&spec=<name>&doc=<proposal|design|tasks> → SPEC 文档原文（found + content）
    POST /api/spec-error-clear?project=<name>&spec=<name> → 在线清除 SPEC 的 error 字段（置空并原子写回 STATE.md）
    POST /api/spec-priority?project=<name>&spec=<name>  → 设置 SPEC 优先级（body: {"priority": 1-9}，400 校验 / 404 / 200）
    POST /api/spec-delete?project=<name>&spec=<name>  → 软删除 SPEC（STATE.md 剔除 + 目录移入 archive，运行中返回 409）
    POST /api/spec-archive?project=<name>&spec=<name> → 归档终态 SPEC（目录移入 archive/YYYY-MM-DD-<name>，STATE.md 保留，仅 done/pushed）
    POST /api/spec-admin-invoke?project=<name>&spec=<name>  → 手动唤起 Admin（写 .fenix/admin_invoke_request.json，进行中返回 409）
    POST /api/spec-start-after?project=<name>&spec=<name> → 设置/清除定时拾取 start_after（body: {"value": iso|null}，非法 400 / 终态 403）
    POST /api/spec-freeze-config?project=<name>&spec=<name> → 冻结管理（body: {"mode": permanent|scheduled|unfreeze, "until"?: iso}，非法 400 / 非冻结 409）
    POST /api/spec-budget?project=<name>&spec=<name> → 设置/清除 per-spec 实现尝试预算覆盖（body: {"budget": 1..budget_max 整数|null}，缺键/非法 400 / 终态 403）
    POST /api/spec-approve-push?project=<name>&spec=<name> → 审批推送 done SPEC（写 .fenix/approve_push_request.json 信号，daemon 未运行/已有信号 409，非 done 403）
    GET /api/config?project=<name> → 读取受管配置（llm / agents.models / gates.approve_mode）
    POST /api/config?project=<name> → 写回受管配置（原子写、校验失败返回 400）
    GET /api/verify-yaml?project=<name> → 验证契约文件 .fenix/verify.yaml 原文（设置页「项目简介」面板）
    POST /api/verify-yaml?project=<name> → 保存验证契约（整文件覆写；YAML 语法 + 顶层映射校验，失败 400）
    POST /api/verify-yaml-autodraft?project=<name> → 触发 AI 起草验证契约（body: {"overwrite"?: bool}；契约有效无 overwrite 返回 skipped，否则派发信号）
    GET /api/verify-yaml-template → 契约模板原文（core/verify_contract_template.yaml，设置页「插入模板」用）
    GET /api/prompts?project=<name> → agent 提示词：通用层（只读）+ 项目级 .fenix/agents/ 附加（缺 project 仅通用层）
    POST /api/prompts?project=<name> → 保存项目附加提示词（body: {"agent_type","content"}；白名单校验、自引用项目拒绝 403）
    GET /api/help/docs → 帮助文档清单 [{name, title}]（docs/help/ 动态读盘，README 置顶）
    GET /api/help/doc?name=<file> → 单篇帮助文档 Markdown 原文（白名单 + 防穿越）
    GET /api/alerts?project=<name> → Administrator 告警/处置记录（缺省跨项目聚合未处理告警）
    POST /api/alerts/<id>/handled?project=<name> → 标记升级告警已处理
    POST /api/alerts/clear → 清理所有事件：全部项目未处理告警一次标记已处理
    GET /api/admin-activities?project=<name> → Administrator 活动记录（运维记录时间线，未处理升级关联置顶）
    GET /screenshots/<project>/<spec>/<file> → 截图（防路径穿越，仅限注册项目）
"""

import gzip
import contextlib
import fcntl
import json
import logging
import mimetypes
import os
import queue
import re
import sys
import signal
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from . import data as dashboard_data
from .registry import Registry
from .watcher import FileWatcher
from core.agent_runner.prompt_builder import (
    AGENT_PROMPT_DIR,
    AGENT_PROMPT_FILES,
    project_agents_dir,
)
from core.fenix_session import start_daemon, stop_daemon
from core.admin_store import AdminStore, SIGNAL

logger = logging.getLogger("fenixd.dashboard.server")

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# 帮助文档目录：core/dashboard/ 上两级 = 框架根（add-dashboard-help-center D2）
FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
HELP_DOCS_DIR = FRAMEWORK_ROOT / "docs" / "help"
# 文档名白名单（add-dashboard-help-center D2）：限定字母/数字/._- + .md，
# 从根上拒绝路径穿越片段；配合 real path 归属校验双保险
HELP_DOC_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.md$")

# 连接上限（dashboard-connection-limit D6，模块常量供测试 monkeypatch）
MAX_SSE_CONNECTIONS = 32  # SSE 活跃连接上限，超出拒绝新连接（客户端退化为轮询）
MAX_SERVER_THREADS = 64  # ThreadingHTTPServer 并发处理线程上限，超限 503
# SSE 客户端断开探测轮询间隔（秒）：队列空时每次等待该时长后探测 FIN。
# 心跳仍按 25s 发送；该间隔仅决定「释放连接槽位」的响应速度。
SSE_CLIENT_POLL_INTERVAL = 1.0


from .sse import SSEConnection, SSEHub  # noqa: F401 — D1 门面 re-export
from .http_server import DashboardHTTPServer  # noqa: F401 — D1 门面 re-export


def find_free_port(start: int, max_attempts: int = 50) -> int:
    """从 start 开始向上探测第一个空闲端口。"""
    for port in range(start, start + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"无法找到空闲端口（{start}~{start + max_attempts - 1} 均被占用）")


@contextlib.contextmanager
def _project_lifecycle_lock(proot: str, timeout: float = 25.0):
    """同一项目启停操作跨请求串行化（fix-supervisor-hosting-chain 验证修复）。

    并发 install-hosting/stop/start 对同一项目并发时，后到请求（HTTP 线程）等待
    前一个完成——杜绝「一路 stop_daemon 超时兜底把另一路刚经 start_daemon 拉起的
    supervisor 误杀」这类互踩（验证实证：install 端点残留执行与下一场景 stop
    并发，后者 SIGKILL 误杀前者新 supervisor）。锁文件 .fenix/lifecycle.lock
    （运行时状态，不进 git；flock 跨进程互斥）。

    超过 timeout 仍未获取到锁 → acquired=False，调用方返回可读错误（避免 HTTP
    挂死逼近客户端 30s 超时线）。获取失败（目录不可写等）同样 acquired=False，
    不阻断操作本身（锁是尽力而为的串行化，不是权限门）。
    """
    lock_dir = Path(proot) / ".fenix"
    lock_path = lock_dir / "lifecycle.lock"
    try:
        lock_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        yield False
        return
    acquired = False
    try:
        deadline = time.time() + max(0.0, timeout)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.time() > deadline:
                    break
                time.sleep(0.2)
        yield acquired
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


# POST 请求体最大字节数（256KB，避免大内存占用）
MAX_POST_BODY = 256 * 1024


from .routes.base import H0BaseMixin  # noqa: E402 — D5 mixin
from .routes.project_routes import H2ProjectRoutesMixin  # noqa: E402
from .routes.spec_routes import H3SpecRoutesMixin  # noqa: E402
from .routes.run_routes import H4RunRoutesMixin  # noqa: E402
from .routes.settings_routes import H5SettingsRoutesMixin  # noqa: E402
from .routes.alert_routes import H6AlertRoutesMixin  # noqa: E402
from .routes.evolution_routes import H7EvolutionRoutesMixin  # noqa: E402
from .routes.help_routes import H8HelpRoutesMixin  # noqa: E402
from .routes.sse_routes import H9SseRoutesMixin  # noqa: E402
from .routes.static_routes import H10StaticRoutesMixin  # noqa: E402
class DashboardHandler(H0BaseMixin, H2ProjectRoutesMixin, H3SpecRoutesMixin, H4RunRoutesMixin, H5SettingsRoutesMixin, H6AlertRoutesMixin, H7EvolutionRoutesMixin, H8HelpRoutesMixin, H9SseRoutesMixin, H10StaticRoutesMixin, BaseHTTPRequestHandler):
    """处理 GET/HEAD/POST/DELETE 请求，输出 JSON 或静态资源。

    protocol_version=HTTP/1.1：SSE 需要 keep-alive 长连接 + chunked 传输
    （普通响应均带 Content-Length，不受影响）。
    """

    server: DashboardHTTPServer  # 类型标注，便于 IDE

    protocol_version = "HTTP/1.1"

    # ── 基础 ─────────────────────────────────────────────────

def _find_dashboard_occupant(port: int) -> dict | None:
    """定位占用目标端口的进程（仅 Linux）。

    返回 {"pid": int, "cmdline": str} 或 None（无占用 / 无法判定）。

    判定（inode 映射，避免 /proc/<pid>/net/tcp 按网络命名空间而非进程返回错误 PID）：
    1. 读 /proc/net/tcp 找到监听 127.0.0.1:port 的 socket inode；
    2. 遍历 /proc/<pid>/fd/* 软链接，匹配 socket:[inode] 得到真正持有该
       端口的 PID；
    3. 读取该进程 cmdline。
    """
    try:
        port_hex = f"{port & 0xffff:04X}"
        inode = None
        net_tcp = Path("/proc/net/tcp")
        if not net_tcp.exists():
            return None
        for line in net_tcp.read_text(encoding="utf-8", errors="replace").split("\n")[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            local = parts[1]
            state = parts[3]
            if state != "0A":  # 0A = LISTEN
                continue
            if ":" not in local:
                continue
            addr, p = local.split(":", 1)
            if p.upper() == port_hex and addr.upper() == "0100007F":
                inode = parts[9]
                break
        if not inode:
            return None
        # 通过 /proc/<pid>/fd 软链接匹配 inode → 真正持有端口的 PID
        for pid_dir in Path("/proc").glob("[0-9]*"):
            fd_dir = pid_dir / "fd"
            if not fd_dir.is_dir():
                continue
            try:
                for link in fd_dir.iterdir():
                    try:
                        target = os.readlink(str(link))
                    except OSError:
                        continue
                    if target == f"socket:[{inode}]":
                        try:
                            raw = (pid_dir / "cmdline").read_bytes()
                            cmdline = raw.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
                        except OSError:
                            cmdline = ""
                        return {"pid": int(pid_dir.name), "cmdline": cmdline}
            except OSError:
                continue
    except Exception:
        return None
    return None


def _is_dashboard_serve_cmd(cmdline: str) -> bool:
    """cmdline 是否为 fenix_dashboard.py --serve 实例。"""
    return "fenix_dashboard.py" in cmdline and "--serve" in cmdline


def _proc_starttime(pid: int) -> int | None:
    """读 /proc/<pid>/stat 的 starttime（第 22 字段）；进程不存在 → None。

    starttime 比对用于防 PID 复用：目标死后 PID 被新进程复用时值必然不同。
    """
    try:
        data = Path(f"/proc/{pid}/stat").read_text()
        # comm 字段可能含空格：从最后一个 ')' 之后取字段（其后首字段=state=第 3 字段）
        fields = data[data.rindex(")") + 2 :].split()
        return int(fields[19])  # 22 - 3 = 19
    except (OSError, ValueError, IndexError):
        return None


def _claude_watchdog_loop(pid: int, starttime: int, on_death, interval: float = 5.0) -> None:
    """轮询目标进程（默认每 5s）； starttime 变化或消失 → on_death() 一次后返回。"""
    while True:
        time.sleep(interval)
        if _proc_starttime(pid) != starttime:
            on_death()
            return


def _start_claude_watchdog(env=None) -> bool:
    """CLAUDE_PID 生命周期绑定（agent 豁免通道的防泄漏阀，2026-09-04 8790 泄漏）。

    agent 经 CLI --serve 自测时用 nohup 后台拉起实例（父 shell 秒退，PDEATHSIG
    不适用——服务须跨 Bash 调用存活），run 结束 claude 进程退出后实例被 init
    收养成孤儿。检测到 agent 环境（CLAUDE_PID 指向存活进程）→ 起 daemon 线程
    轮询该进程（starttime 比对防 PID 复用），目标消失 → 自杀 SIGTERM。

    纯人 CLI（无 CLAUDE_PID 或目标已死）→ False，长驻豁免行为不变。
    """
    env = os.environ if env is None else env
    try:
        pid = int(env.get("CLAUDE_PID", ""))
    except ValueError:
        return False
    starttime = _proc_starttime(pid)
    if starttime is None:
        return False

    def _terminate():
        sys.stderr.write(
            "dashboard serve 检测到拉起它的 claude 进程已退出（CLAUDE_PID="
            f"{pid}）——agent run 已结束，本实例自杀以避免孤儿泄漏。\n"
        )
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(
        target=_claude_watchdog_loop,
        args=(pid, starttime),
        kwargs={"on_death": _terminate},
        daemon=True,
        name="claude-watchdog",
    ).start()
    return True


def _bind_parent_lifecycle() -> None:
    """父子生命周期绑定（孤儿实例防护，2026-09-03 runs 删空事故 V1 防线）。

    调试/验证脚本直接 `import serve()` 起实例后，脚本退出会把实例孤儿化
    （PPID→1 被 systemd 收养），孤儿实例以启动时代码长期服务端口——事故中
    4 个孤儿实例以 8 月底旧码（自动清理直接删除）持续清理真实项目 runs。
    两道防线：

    1. PR_SET_PDEATHSIG：父进程死亡时内核自动向本进程发 SIGTERM（泄漏即死）；
    2. 启动时已是孤儿（PPID==1）→ 拒绝启动（兜住 nohup/已孤儿化的直接调用）。

    人的显式入口 fenix_dashboard.py --serve 设 FENIX_DASHBOARD_DETACH=1 豁免
    （长驻服务不随启动 shell 退出而终止）。先设 PDEATHSIG 再查 PPID，覆盖
    「检查间隙父进程死亡」的竞态窗口。

    豁免非无条件裸奔（2026-09-04 8790 泄漏）：agent 经 CLI 自测拉起时环境带
    CLAUDE_PID，此时豁免 PDEATHSIG 但装配 claude-watchdog（绑定 claude 进程
    生命周期，run 结束实例自杀）；纯人 CLI（无 CLAUDE_PID）豁免不变。
    """
    if os.environ.get("FENIX_DASHBOARD_DETACH") == "1":
        _start_claude_watchdog()
        return
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        # PR_SET_PDEATHSIG = 1（linux/sched.h）；SIGTERM = 15
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(PR_SET_PDEATHSIG) failed")
    except Exception as e:  # 非 Linux / libc 不可用：仅告警不阻断启动
        sys.stderr.write(
            f"dashboard serve 无法设置 PDEATHSIG（{e}）；"
            "父进程退出后本实例不会自动终止，请注意。\n"
        )
    if os.getppid() == 1:
        sys.stderr.write(
            "dashboard serve 检测到父进程已退出（PPID=1，孤儿启动）——拒绝启动。\n"
            "长驻/后台运行请使用 fenix_dashboard.py --serve 入口，"
            "或显式设置 FENIX_DASHBOARD_DETACH=1。\n"
        )
        sys.exit(1)


def serve(registry: Registry, port: int = 8787, static_dir=None):
    """启动 Dashboard 服务（阻塞）。

    端口独占语义（dashboard-instance-lifecycle）：目标端口被占用时，
    - 占用者为旧的 `fenix_dashboard.py --serve` 实例 → SIGTERM 终止旧实例，
      等待其退出（≤3s）后重新绑定一次；
    - 占用者为其它进程（非 dashboard 实例）→ 打印占用信息后非 0 退出；
    - 任何启动失败 MUST 在 5 秒内退出，不留僵尸实例。
    仅对最终确定的单一端口做上述占用检测（不再自动上探）。

    父子生命周期绑定（孤儿实例防护）：非豁免调用（FENIX_DASHBOARD_DETACH
    未设 1）启动即挂 PR_SET_PDEATHSIG 并拒绝孤儿启动，见 _bind_parent_lifecycle。
    """
    _bind_parent_lifecycle()
    actual = port
    try:
        httpd = DashboardHTTPServer(
            ("127.0.0.1", actual),
            registry,
            static_dir or STATIC_DIR,
        )
    except OSError as e:
        if not isinstance(e, OSError) or e.errno not in (98, 48, 56):
            # 非「地址已占用」错误（如权限）直接抛出
            raise
        # EADDRINUSE：地址已被占用 → 端口接管逻辑
        occupant = _find_dashboard_occupant(actual)
        if occupant and _is_dashboard_serve_cmd(occupant["cmdline"]):
            try:
                os.kill(occupant["pid"], signal.SIGTERM)
            except OSError:
                pass
            # 等待旧实例退出（≤3s）
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if not _is_process_alive(occupant["pid"]):
                    break
                time.sleep(0.1)
            # 重新绑定一次
            try:
                httpd = DashboardHTTPServer(
                    ("127.0.0.1", actual),
                    registry,
                    static_dir or STATIC_DIR,
                )
            except OSError as e2:
                sys.stderr.write(f"端口 {actual} 接管旧 dashboard 实例后仍无法绑定：{e2}\n")
                sys.exit(1)
        else:
            # 占用者为非 dashboard 进程（或无法判定）→ 明确报错非 0 退出
            info = occupant["cmdline"] if occupant else "未知进程"
            pid = occupant["pid"] if occupant else "?"
            sys.stderr.write(
                f"端口 {actual} 已被占用（PID {pid}，cmdline: {info}）；\n"
                f"该占用者不是 fenix_dashboard.py --serve 实例，恕不接管。\n"
                f"请释放该端口后重试，或使用其它 --port。\n"
            )
            sys.exit(1)

    watcher = FileWatcher(
        lambda: httpd.projects(), httpd.sse_hub, summary_index=httpd.summary_index
    )
    httpd.watcher = watcher
    watcher.start()
    url = f"http://localhost:{actual}"
    # flush=True：被 Ctrl+C / timeout 杀进程时 URL 必须已输出（供 skill 解析）
    print("=" * 60, flush=True)
    print("  Fenix Web Dashboard", flush=True)
    print(f"  地址: {url}", flush=True)
    print(f"  端口: {actual}", flush=True)
    print("  Ctrl+C 退出", flush=True)
    print("=" * 60, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard 已退出")
    finally:
        watcher.stop()
        httpd.server_close()


def _is_process_alive(pid: int) -> bool:
    """进程是否存活（/proc/<pid> 目录存在即视为存活，Linux 限定）。"""
    try:
        return Path(f"/proc/{pid}").exists()
    except OSError:
        return False

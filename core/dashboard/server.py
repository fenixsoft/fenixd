"""
server.py — Fenix Web Dashboard 服务器（dashboard-server）。

- 基于 Python 标准库 http.server.ThreadingHTTPServer，零新增依赖（D2）。
- 仅绑定 127.0.0.1，默认端口 8787；被占用时由 serve() 执行端口接管语义
  （dashboard-instance-lifecycle）：旧 dashboard --serve 实例自动终止接管，
  非 dashboard 进程占用则报错退出，绝不静默僵挂。
- REST JSON API + 截图等静态资源服务。
- 所有 API 容错：数据源损坏以字段标记返回，不 500。

端点（代表性摘录，非完整清单；完整端点以 core/dashboard/routes/ 各 mixin 的实际注册为准）：
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

    ……以上仅为代表性摘录：spec-freeze / spec-activate / spec-resume /
    spec-task-reflow / spec-promote / spec-re-review / spec-unfreeze、
    run-cancel、hooks/audit 以及 code-review / regression / evolution /
    session / knowledge / architecture 等路由 mixin 的端点族均未列入，
    完整清单以 routes/ 各 mixin 的实际注册为准，此处不逐一维护。
"""

import contextlib
import fcntl
import logging
import os
import re
import sys
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import data as dashboard_data
from .registry import Registry
from .watcher import FileWatcher
from core.agent_runner.prompt_builder import (
    AGENT_PROMPT_DIR,
    AGENT_PROMPT_FILES,
    project_agents_dir,
)
from core.fenix_session import start_daemon, stop_daemon
from core.proc_utils import find_free_port as _proc_find_free_port

logger = logging.getLogger("fenixd.dashboard.server")

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# 帮助文档目录：core/dashboard/ 上两级 = 框架根（add-dashboard-help-center D2）
FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
HELP_DOCS_DIR = FRAMEWORK_ROOT / "docs" / "help"
# 文档名白名单（add-dashboard-help-center D2）：限定字母/数字/._- + .md，
# 从根上拒绝路径穿越片段；配合 real path 归属校验双保险
HELP_DOC_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.md$")
# 帮助中心菜单显式顺序（阅读动线，不再依赖文件名字典序）；未列入的文档
# 按文件名字典序追加在有序文档之后（新增文档不登记也会出现在清单末尾）
HELP_DOC_ORDER = [
    "README.md",            # 一、Fenix 帮助中心（默认文档）
    "01-quick-start.md",    # 快速上手
    "02-concepts.md",       # 核心概念与架构
    "03-lifecycle.md",      # 生命周期与状态机
    "06-governance.md",     # 调度与治理规则
    "05-verification.md",   # 验证体系
    "07-safeguards.md",     # 保障机制
    "09-config.md",         # 配置参考
    "11-logs.md",           # 日志体系
    "knowledge-atlas.md",   # 知识真相源
    "10-artifacts.md",      # 文件与数据地图
    "04-cli.md",            # CLI 操作手册
    "08-dashboard.md",      # Dashboard 操作手册
    "12-faq.md",            # FAQ 与故障排查
]

# 连接上限（dashboard-connection-limit D6，模块常量供测试 monkeypatch）
MAX_SSE_CONNECTIONS = 32  # SSE 活跃连接上限，超出拒绝新连接（客户端退化为轮询）
MAX_SERVER_THREADS = 64  # ThreadingHTTPServer 并发处理线程上限，超限 503
# SSE 客户端断开探测轮询间隔（秒）：队列空时每次等待该时长后探测 FIN。
# 心跳仍按 25s 发送；该间隔仅决定「释放连接槽位」的响应速度。
SSE_CLIENT_POLL_INTERVAL = 1.0


from .sse import SSEConnection, SSEHub  # noqa: F401 — D1 门面 re-export
from .http_server import DashboardHTTPServer  # noqa: F401 — D1 门面 re-export


def find_free_port(start: int = 0, max_attempts: int = 50) -> int:
    """兼容壳：转发 core.proc_utils.find_free_port（code-review ca8a69e04fda）。

    原上探实现（bind 逐个试、成功即关闭返回）已删除——与 proc_utils 版同名
    双实现并存，且生产调用方（core/verify_contract.py、core/v2_dev_server.py、
    core/pm_engine/verification/serving.py）早已全部切换到 proc_utils 版本；
    此处仅保留同名入口供既有测试调用方（tests/conftest.py 等）过渡，端口分配
    逻辑单一来源化。``start`` / ``max_attempts`` 不再参与分配（由 OS bind 0
    分配临时端口）；需要消除「探测到正式启动」竞态窗口的新调用方请改用
    core.proc_utils.find_bound_socket（持有已绑定 socket 直到正式启动）。
    """
    return _proc_find_free_port()


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
        # code-review item 2cec7f58ab54：deadline 用 monotonic 时钟（秒，语义
        # 不变）——墙上时钟回拨会延长 flock 竞争等待，令 HTTP 线程持等逼近
        # 客户端 30s 超时线；与 serve() 接管等待的时钟选择对齐。
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() > deadline:
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
from .routes.session_routes import H_SessionRoutesMixin  # noqa: E402
from .routes.code_review_routes import H11CodeReviewRoutesMixin  # noqa: E402
from .routes.regression_routes import H12RegressionRoutesMixin  # noqa: E402
from .routes.architecture_routes import H13ArchitectureRoutesMixin  # noqa: E402
from .routes.knowledge_routes import H14KnowledgeRoutesMixin  # noqa: E402
from .routes.topology_routes import H15TopologyRoutesMixin  # noqa: E402
from .routes.command_center_routes import H17CommandCenterRoutesMixin  # noqa: E402
class DashboardHandler(H0BaseMixin, H2ProjectRoutesMixin, H3SpecRoutesMixin, H4RunRoutesMixin, H5SettingsRoutesMixin, H6AlertRoutesMixin, H7EvolutionRoutesMixin, H8HelpRoutesMixin, H9SseRoutesMixin, H10StaticRoutesMixin, H_SessionRoutesMixin, H11CodeReviewRoutesMixin, H12RegressionRoutesMixin, H13ArchitectureRoutesMixin, H14KnowledgeRoutesMixin, H15TopologyRoutesMixin, H17CommandCenterRoutesMixin, BaseHTTPRequestHandler):
    """处理 GET/HEAD/POST/DELETE 请求，输出 JSON 或静态资源。

    protocol_version=HTTP/1.1：SSE 需要 keep-alive 长连接 + chunked 传输
    （普通响应均带 Content-Length，不受影响）。
    """

    server: DashboardHTTPServer  # 类型标注，便于 IDE

    protocol_version = "HTTP/1.1"

    # 方法实现见各 mixin（routes/ 下 H0 起各 mixin）

def _find_dashboard_occupant(port: int) -> dict | None:
    """定位占用目标端口的进程（仅 Linux）。

    返回 {"pid": int, "cmdline": str} 或 None（无占用 / 无法判定）。

    判定（inode 映射，避免 /proc/<pid>/net/tcp 按网络命名空间而非进程返回错误 PID）：
    1. 读 /proc/net/tcp（及 /proc/net/tcp6）找到监听目标端口的 socket inode，
       地址匹配 127.0.0.1 / 0.0.0.0 通配（IPv4）与 :: 通配 / ::1（IPv6）
       （code-review item 9df14cc4442f）；
    2. 遍历 /proc/<pid>/fd/* 软链接，匹配 socket:[inode] 得到真正持有该
       端口的 PID；
    3. 读取该进程 cmdline。
    """
    try:
        port_hex = f"{port & 0xffff:04X}"
        # 匹配形态放宽（code-review item 9df14cc4442f）：bind 127.0.0.1:port 对
        # 0.0.0.0 通配、IPv6 通配（::）或 ::1 上的监听同样 EADDRINUSE，旧实现
        # 只扫 IPv4 表 /proc/net/tcp 且仅认 0100007F，此时定位不到占用者、
        # serve() 只能报「未知进程（PID ?）」。现补充扫描 /proc/net/tcp6（禁用
        # IPv6 的机器上该文件不存在，按无此表跳过）；IPv6 地址列 32 hex、按
        # 32 位字小端打印，通配 :: 为全零、::1 为 …01000000。匹配不上仍返回
        # None——「匹配不上即不接管」的保守语义不变。
        v4_addrs = ("0100007F", "00000000")  # 127.0.0.1 / 0.0.0.0 通配
        v6_addrs = (
            "0" * 32,  # :: 通配
            "00000000000000000000000001000000",  # ::1
        )
        inode = None
        for net_table, listen_addrs in (
            (Path("/proc/net/tcp"), v4_addrs),
            (Path("/proc/net/tcp6"), v6_addrs),
        ):
            if not net_table.exists():
                continue
            for line in net_table.read_text(
                encoding="utf-8", errors="replace"
            ).split("\n")[1:]:
                parts = line.split()
                # 字段数护栏按实际取用下标（inode 是第 10 列）判定（code-review item
                # aaf3f304a0de）：旧实现只查 `len(parts) < 4`，而下方读 `parts[9]`——
                # 4~9 个字段的截断/畸形行会抛 IndexError，被外层 `except Exception:
                # return None` 吞掉，使「解析失败」与「无占用者」不可区分；调用方据此
                # 打印误导性的「未知进程」并非 0 退出，而不是接管陈旧 dashboard 实例。
                if len(parts) < 10:
                    continue
                local = parts[1]
                state = parts[3]
                if state != "0A":  # 0A = LISTEN
                    continue
                if ":" not in local:
                    continue
                addr, p = local.split(":", 1)
                if p.upper() == port_hex and addr.upper() in listen_addrs:
                    inode = parts[9]
                    break
            if inode:
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
                        pid = int(pid_dir.name)
                        # starttime 随 PID 一并返回（code-review item 5612e191a8f5）：
                        # 接管方 kill 前可据此复核进程身份，防「查询后目标死亡、PID
                        # 被复用」时误杀无关进程。
                        return {"pid": pid, "cmdline": cmdline, "starttime": _proc_starttime(pid)}
            except OSError:
                continue
    except Exception as e:
        # 探测失败≠无占用者（code-review item 532de62ce081）：兜底仍返回 None
        # 保持行为不变，但写一行 stderr 留痕，与「端口确实空闲」区分，便于排查。
        sys.stderr.write(f"dashboard 端口占用者探测异常（按无占用者处理）: {e}\n")
        return None
    return None


def _is_dashboard_serve_cmd(cmdline: str) -> bool:
    """cmdline 是否为 fenix_dashboard.py --serve 实例。

    按 argv 匹配（code-review item 05269db8b9cb）：文档惯例启动形态是
    `python3 fenix_dashboard.py --serve`，argv[0] 是解释器而非脚本，只认
    argv[0]（c36c3fc10722 收紧后的判据）会把真实旧实例恒判 False、接管
    语义永不生效——故遍历全部 argv 项：存在某项 basename 恰为
    fenix_dashboard.py 且另一项严格等于 --serve 即命中。仍守住
    c36c3fc10722 的防误杀语义：--serve 用严格等号而非子串匹配（--server/
    --servable 等前缀参数不误命中）；编辑器/打包脚本仅引用脚本路径时不
    会同时携带独立的 --serve 参数项，不误判。_find_dashboard_occupant
    返回的 cmdline 由 /proc/<pid>/cmdline 以 NUL→空格还原，故按空白切分
    回 argv 逐项比对。
    """
    argv = cmdline.split()
    return "--serve" in argv and "fenix_dashboard.py" in {
        os.path.basename(a) for a in argv
    }


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


def _claude_watchdog_loop(
    pid: int, starttime: int, on_death, interval: float = 5.0, stop_event=None
) -> None:
    """轮询目标进程（默认每 5s）； starttime 变化或消失 → on_death() 一次后返回。

    stop_event 置位即停止轮询（既不判死也不触发 on_death）——测试环境装配的
    watchdog 由收割口（stop_all_claude_watchdogs / conftest autouse）在用例
    边界停掉，MUST NOT 让泄漏线程在套件收尾阶段执行 on_death 自杀扳机
    （2026-10-07 团灭事故：89 个泄漏 watchdog 在负载窗口误判死亡，齐射
    os.kill(自身, SIGTERM) 团灭全量回归）。

    code-review item 2086ce927c5e：区分「进程不存在」与「/proc 读取失败」。
    _proc_starttime 在 OSError（如 /proc 重挂载、fd 耗尽）下也返回 None，原实现
    单次读取失败即等价「目标已死」触发自杀。现按 /proc/<pid> 目录是否仍在区分：
    目录消失（进程真死）或读到不同 starttime（PID 复用实锤）→ 立即判死，保持
    既有 fail-safe；进程仍在但读不到 → 视为瞬时读取失败，连续 3 次（≈15s）才
    判死，首次失败 stderr 留痕一次，避免瞬时读错误误自杀。
    """
    read_failures = 0
    warned = False
    while True:
        if stop_event is not None:
            if stop_event.wait(interval):
                return  # 收割停止：不判死、不触发 on_death
        else:
            time.sleep(interval)
        cur = _proc_starttime(pid)
        if cur == starttime:
            read_failures = 0
            continue
        if cur is not None or not Path(f"/proc/{pid}").exists():
            # 读到不同 starttime（PID 复用）或进程已消失 → 判死
            on_death()
            return
        # 进程仍在但 starttime 读不到：按瞬时读取失败宽限，连续 3 次才判死
        read_failures += 1
        if not warned:
            warned = True
            sys.stderr.write(
                f"claude-watchdog 目标 PID {pid} starttime 读取失败（进程仍在，"
                f"连续 {read_failures}/3 次）——暂不判死，继续观察。\n"
            )
        if read_failures >= 3:
            on_death()
            return


def _is_tmux_hosted(ppid: int | None = None) -> bool:
    """给定 pid（默认 os.getppid()）判断其是否为 tmux server（显式长驻判据）。

    2026-09-22 8787 误杀事故：tmux server 会把启动 shell 的 CLAUDE_PID 当普通
    环境变量继承进 pane，人工常驻实例被 claude-watchdog 误绑到某个 Claude 会话，
    会话续接/分叉/退出即自杀。主判据读 /proc/<ppid>/comm 恰为 "tmux: server"；
    comm 可读但不匹配才回退 /proc/<ppid>/cmdline，且仅当 argv[0] 的 basename
    恰为 "tmux" 或以 "tmux:" 开头才命中——不用「argv 任一项含 tmux 子串」
    （agent 自测包装脚本作父进程时 argv[0] 形如 .../tmux_selftest.sh，子串命中
    会把 agent 自测实例误判为常驻、漏掉防泄漏）。读取失败（非 Linux / /proc
    不可用 / 进程已退出）→ False，按非长驻处理保持 watchdog 既有防泄漏
    （fail-safe 偏向防泄漏）。父进程身份不随环境变量继承传播，判据不受
    TMUX 透传污染。
    """
    if ppid is None:
        ppid = os.getppid()
    try:
        # 字节读 + replace 解码：comm 可经 PR_SET_NAME 写入任意字节，严格解码的
        # UnicodeDecodeError（ValueError）会逃逸 OSError 处理器、违反「读取失败
        # → False」的 fail-safe 契约（code-review 发现）
        comm = Path(f"/proc/{ppid}/comm").read_bytes().decode("utf-8", "replace").strip()
    except OSError:
        return False
    if comm == "tmux: server":
        return True
    try:
        argv0 = Path(f"/proc/{ppid}/cmdline").read_bytes().split(b"\0")[0]
    except OSError:
        return False
    base = os.path.basename(argv0.decode("utf-8", "replace"))
    return base == "tmux" or base.startswith("tmux:")


def _parent_is_tmux_server(pid: int) -> bool:
    """给定占用者 pid，判定其是否 tmux 承载（祖先链上存在 tmux server）。

    2026-09-29 事故：agent 自测实例启动时，接管逻辑识别占用者为旧 --serve
    实例后无差别 SIGTERM，杀掉 tmux 承载的人工常驻 dashboard（pane 进程死 →
    单窗口 tmux 会话消失），接管者自身带 watchdog 自杀——用户可访问实例静默
    死亡。本判据在 kill 前对占用者做与 _is_tmux_hosted 同源的长驻判定：
    读 /proc/<pid>/stat 取 ppid（解析纪律同 _proc_starttime——comm 可能含
    空格，从最后一个 ')' 之后切片取字段），沿祖先链上溯逐层调
    _is_tmux_hosted(祖先 pid)。

    必须上溯而非只查一层：`tmux new-session -d "... --serve"`（sh -c exec）
    形态下占用者父进程恰为 tmux server，但人工常驻的主流形态是 pane 交互
    shell 里手动启动——占用者的直接父进程是 pane shell（bash/zsh），
    tmux server 是祖父。只查一层会把 pane shell 的 comm 当判定对象，
    豁免永不命中、SIGTERM 照发（2026-09-30 真实环境场景验证实证）。
    上溯深度取 4：tmux 承载最多 2 跳，余量给包装脚本层。

    读取/解析失败（/proc 不可用、祖先已退出、占用者已退出成孤儿等）→
    False：接管路径按非 tmux 承载放行既有接管。方向与 _is_tmux_hosted 的
    「读取失败 → False」纪律一致，但语义不同：此处 fail-safe 偏向放行——
    孤儿化实例已无 tmux 会话可依归，收割它不破坏任何常驻形态。
    """
    current = pid
    for _ in range(4):
        try:
            data = Path(f"/proc/{current}/stat").read_text()
            # ')' 后首字段=state（第 3 字段），次字段=ppid（第 4 字段）
            fields = data[data.rindex(")") + 2 :].split()
            current = int(fields[1])
        except (OSError, ValueError, IndexError):
            return False
        if current <= 1:
            return False
        if _is_tmux_hosted(current):
            return True
    return False


# 本进程内全部在飞 claude-watchdog 的停止口（(stop_event, thread) 注册表）。
# 收割口 stop_all_claude_watchdogs 消费；serve() 优雅停机链与 tests/conftest
# 的用例边界收割 fixture 各自调用。锁保护注册/收割的并发（watchdog 装配点
# 在请求线程/测试线程，收割在停机线程/conftest）。
_ACTIVE_WATCHDOG_STOPS: list = []
_ACTIVE_WATCHDOG_LOCK = threading.Lock()


def stop_all_claude_watchdogs() -> int:
    """停掉本进程内全部 claude-watchdog 线程（置 stop_event，不 join 阻塞）。

    返回本次收割的线程数。收割语义是「拆除自杀扳机」：被停的 watchdog MUST
    NOT 再执行 on_death（stop_event.wait 返回 True 即裸退出，见
    _claude_watchdog_loop）——泄漏线程在套件收尾阶段的判死误自杀正是
    2026-10-07 团灭事故的根因。不 join：调用方（serve finally / conftest
    teardown）不应被 5s 轮询间隔拖住，线程最迟一个 interval 内自行退出。
    """
    with _ACTIVE_WATCHDOG_LOCK:
        entries, _ACTIVE_WATCHDOG_STOPS[:] = _ACTIVE_WATCHDOG_STOPS[:], []
    stopped = 0
    for event, thread in entries:
        event.set()
        stopped += 1
    return stopped


def _start_claude_watchdog(env=None) -> bool:
    """CLAUDE_PID 生命周期绑定（agent 豁免通道的防泄漏阀，2026-09-04 8790 泄漏）。

    agent 经 CLI --serve 自测时用 nohup 后台拉起实例（父 shell 秒退，PDEATHSIG
    不适用——服务须跨 Bash 调用存活），run 结束 claude 进程退出后实例被 init
    收养成孤儿。检测到 agent 环境（CLAUDE_PID 指向存活进程）→ 起 daemon 线程
    轮询该进程（starttime 比对防 PID 复用），目标消失 → 自杀 SIGTERM。

    纯人 CLI（无 CLAUDE_PID 或目标已死）→ False，长驻豁免行为不变。

    tmux 承载（父进程为 tmux server）→ 显式人工常驻，不装配（2026-09-22 8787
    误杀事故）。不可用自身 TMUX 环境变量判定长驻：daemon 由 tmux 下 supervisor
    启动，其 TMUX 会被 agent_runner（os.environ.copy() 不清洗）透传给 agent
    子进程，agent nohup 自测实例同样带 TMUX，会把临时自测实例误判为常驻、漏掉
    防泄漏；父进程是否为 tmux 无此继承污染，判据见 _is_tmux_hosted。
    """
    if _is_tmux_hosted():
        return False
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
        # SIGTERM 的处置已由 serve() 安装为「优雅停机」（转 httpd.shutdown()，
        # code-review item a4e9b12a8b82），故此处 SIGTERM 会走完整清理链
        # （session_manager.shutdown / watcher.stop / server_close），
        # 不再依赖默认处置的「立即终止、不展开 Python 帧」。
        os.kill(os.getpid(), signal.SIGTERM)

    _stop = threading.Event()
    thread = threading.Thread(
        target=_claude_watchdog_loop,
        args=(pid, starttime),
        kwargs={"on_death": _terminate, "stop_event": _stop},
        daemon=True,
        name="claude-watchdog",
    )
    # 先登记后 start（同一把锁内完成）：若先 start 后登记，收割口恰在两步之间
    # 执行会永久漏掉该 watchdog，残留线程误判死亡仍会触发 on_death 自杀扳机；
    # 事件先于线程启动被置位时，循环首轮 stop_event.wait 即返回 True 裸退出。
    with _ACTIVE_WATCHDOG_LOCK:
        _ACTIVE_WATCHDOG_STOPS.append((_stop, thread))
        thread.start()
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
      等待其退出（≤9s）后重新绑定一次；但占用者为 tmux 承载的常驻实例
      （父进程为 tmux server，见 _parent_is_tmux_server）→ 不发任何信号，
      打印含 PID 与 --port 换端口指引的错误后非 0 退出（2026-09-29 事故）；
    - 占用者为其它进程（非 dashboard 实例）→ 打印占用信息后非 0 退出；
    - 启动失败退出时限（code-review item a5c3c97d255b）：非接管失败立即
      退出；非 tmux 旧实例接管路径在 SIGTERM 后等待旧实例退出最长 9 秒、
      重绑仍失败才 exit(1)，最坏 ~9 秒——依赖「5 秒内失败」时限的调用方
      （agent 自适应换端口、探活脚本）勿按 5 秒判断。均不留僵尸实例。
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
        if e.errno not in (98, 48, 56):
            # 非「地址已占用」错误（如权限）直接抛出。
            # code-review item fde33bdc20b2：旧写法 `not isinstance(e, OSError) or ...`
            # 的首操作数恒为 False（e 已由 except 绑定为 OSError），系死代码；
            # 实际判据就是 errno，此处化简约。
            # errno 逐值语义（code-review item 33e07020156d）：98=Linux EADDRINUSE、
            # 48=macOS EADDRINUSE——errno 常量取值随平台不同，这里按字面量并列做
            # 跨平台兜底；56=Linux EALREADY，本义「连接已在进行」，并无「地址已
            # 占用」语义，收录理由初版提交 6393f97d 未说明、已不可考。移除属行为
            # 变更（可能改变既有环境的接管路径实测面），保守保留判据不变。
            raise
        # EADDRINUSE：地址已被占用 → 端口接管逻辑
        occupant = _find_dashboard_occupant(actual)
        if occupant and _is_dashboard_serve_cmd(occupant["cmdline"]):
            # 复核进程身份（code-review item 5612e191a8f5）：occupant 的 PID 来自
            # 早先 /proc 扫描，若目标在查表与 kill 之间死亡、PID 被复用，直接
            # SIGTERM 会误杀无关进程。用查表时记录的 starttime 比对（同
            # _claude_watchdog_loop 的 PID 复用防护），不一致则视为目标已消失、
            # 不再发信号（端口若仍被占，下方重绑会失败并明确报错）。
            expected_start = occupant.get("starttime")
            identity_gone = (
                expected_start is None or _proc_starttime(occupant["pid"]) != expected_start
            )
            if identity_gone:
                # 身份复核不一致（code-review item e15cefc5aa28）：占用者可能恰在
                # 「bind 失败→查表→复核」间隙自然退出（或 /proc 瞬时读取失败令
                # starttime 读成 None），端口此刻或已空闲——先试一次免信号重绑，
                # 仅重绑仍失败才报错退出；保守方向不变，绝不向身份存疑的 PID
                # 发送任何信号。
                try:
                    httpd = DashboardHTTPServer(
                        ("127.0.0.1", actual),
                        registry,
                        static_dir or STATIC_DIR,
                    )
                except OSError as e2:
                    sys.stderr.write(
                        f"端口 {actual} 占用者 PID {occupant['pid']} 身份已变化/已退出，"
                        f"跳过接管信号（防 PID 复用误杀）；重绑仍失败: {e2}"
                        f"——端口可能仍被占用，可稍后重试或用 --port 换端口。\n"
                    )
                    sys.exit(1)
                sys.stderr.write(
                    f"端口 {actual} 原占用者已退出，免信号重绑成功"
                    f"（未向身份存疑的 PID {occupant['pid']} 发送任何信号）。\n"
                )
            if not identity_gone:
                # 常驻豁免（2026-09-29 事故）：占用者父进程为 tmux server → 人工
                # 常驻实例，MUST NOT 发送任何信号（pane 进程死 → 单窗口 tmux 会话
                # 消失、用户可访问实例静默死亡）。打印可操作错误后非 0 退出；
                # agent 自适应换端口，非 tmux 旧实例（agent 自测/nohup 遗留）接管
                # 语义不变。
                if _parent_is_tmux_server(occupant["pid"]):
                    sys.stderr.write(
                        f"端口 {actual} 已被 tmux 承载的常驻 dashboard 实例占用"
                        f"（占用者 PID {occupant['pid']}）——常驻实例不可被接管，"
                        f"未向其发送任何信号。\n"
                        f"请用 --port 指定其它端口，或直接复用常驻实例。\n"
                    )
                    sys.exit(1)
                try:
                    os.kill(occupant["pid"], signal.SIGTERM)
                except OSError as e:
                    # 目标在查表后已退出属可预期竞态，记日志而非静默 pass
                    # （code-review item 5612e191a8f5）。
                    sys.stderr.write(
                        f"端口 {actual} 接管：向 PID {occupant['pid']} 发 SIGTERM 失败"
                        f"（目标可能已退出）: {e}\n"
                    )
                # 等待旧实例退出（≤9s）。SIGTERM 在本模块内是 graceful 退出
                # （_graceful_term → httpd.shutdown → finally 清理链：watcher/
                # SSE/session_manager 收尾），实测空闲实例 ≈4.3s 进程才消失——
                # 初版 3s 窗口不等旧实例死透就重绑，必然再撞 EADDRINUSE、新实例
                # 报错退出（2026-09-30 真实环境场景验证实证：「非 tmux 旧实例仍
                # 接管」的「终止旧实例并成功绑定」时序破裂）。
                deadline = time.monotonic() + 9.0
                while time.monotonic() < deadline:
                    if not _is_process_alive(occupant["pid"]) or _proc_state(occupant["pid"]) == "Z":
                        # 僵尸态旧实例已终止、不再持有监听 socket，仅因父进程未收割
                        # 而 /proc 目录仍在——继续等待只会拖满 9s 窗口（code-review
                        # item 10ab31b04112），视同已退出立即重绑。
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

    # 优雅停机信号处理（code-review item a4e9b12a8b82）：SIGTERM 若走默认处置会
    # 立即终止进程、不展开 Python 帧——serve() 的 finally 清理链（session_manager
    # .shutdown / watcher.stop / server_close）永不执行，live-session 子进程被
    # 孤儿化（正是 self-watchdog 自杀 / 外部 stop 要防的形态）。安装 handler 把
    # SIGTERM 转为 httpd.shutdown()（从 serve_forever 干净返回 → 走 finally）。
    # handler 闭包只引用 httpd（绑定/接管完成后即已存在），故在 watcher /
    # SessionManager 创建**之前**安装：若晚于它们，启动窗口内到达的 SIGTERM 仍走
    # 默认处置、孤儿化刚拉起的会话子进程（code-review item 26f606839a26）。窗口
    # 内提前到达的信号只会置位 shutdown 请求，serve_forever 启动即返回 → 同样走
    # 完整清理链。仅在主线程可安装（signal.signal 限制）；失败（非主线程调用
    # serve）降级为既有默认处置。
    try:
        def _graceful_term(_signum, _frame):
            # httpd.shutdown() MUST 从 serve_forever 所在线程**之外**调用（其内部
            # 等 serve_forever 循环退出，同线程调用会死锁）。signal handler 在
            # 主线程中断点执行、而主线程正阻塞在 serve_forever 内，故起一个极短命
            # 线程调用 shutdown()，让 serve_forever 干净返回 → 走 finally 清理链。
            threading.Thread(target=httpd.shutdown, daemon=True).start()

        signal.signal(signal.SIGTERM, _graceful_term)
    except (ValueError, OSError):
        pass

    watcher = None
    try:
        watcher = FileWatcher(
            lambda: httpd.projects(), httpd.sse_hub, summary_index=httpd.summary_index
        )
        httpd.watcher = watcher
        watcher.start()
        # dashboard-live-session 3.2：会话管理器随 dashboard 生命周期（watcher 之后创建）
        from .session_manager import SessionManager
        httpd.session_manager = SessionManager(httpd.sse_hub)
    except Exception:
        # 绑定成功后的启动段抛异常时，旧实现会让异常逃出 serve() 而**不经过**
        # 下方 finally 的 server_close()，泄漏已绑定的监听 socket（in-process
        # 调用方——验证脚本/测试——常见）。此处显式清理后重抛
        # （code-review item 1a0dcb04539b）。
        # 首先拆除 claude-watchdog 自杀扳机（code-review item da7574bc8958）：
        # _bind_parent_lifecycle 在 FENIX_DASHBOARD_DETACH=1 且带 CLAUDE_PID 时
        # 先于绑定即已装配 watchdog；本异常若被进程内调用方捕获后继续运行，
        # 泄漏的 watchdog 线程仍可能此后误判 CLAUDE_PID 死亡而向本进程发
        # SIGTERM（与 finally 收尾链已设防的形态同型）。收割失败不得阻断
        # 后续清理（同 finally 收尾链纪律）。
        try:
            stop_all_claude_watchdogs()
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"dashboard 启动段收割 claude-watchdog 失败: {e}\n")
        try:
            if httpd.session_manager is not None:
                httpd.session_manager.shutdown()
                httpd.session_manager = None
        except Exception:
            pass
        try:
            if watcher is not None:
                watcher.stop()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
        raise
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
        # 首先拆除 claude-watchdog 自杀扳机（2026-10-07 团灭事故防线）：
        # 本进程装配的 watchdog 线程在停机阶段若仍在轮询，负载窗口的
        # /proc 读取失败可能误判目标死亡而齐射 os.kill(自身, SIGTERM)，
        # 与下方清理链并发。收割失败不得阻断后续清理（同下方逐项纪律）。
        try:
            stop_all_claude_watchdogs()
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"dashboard 退出收割 claude-watchdog 失败: {e}\n")
        # 收割路由侧在飞 claude 起草子进程（code-review item dffc01af10fa）：
        # architecture/refresh 与 regression/autodraft 在 HTTP 线程内以
        # start_new_session=True 拉起的 claude 处于独立会话组，不随本进程
        # 退出而终止；daemon_threads 丢弃阻塞在 communicate() 的线程后，孤儿
        # 仍以 bypassPermissions 写目标项目文件（diagram.html/evidence.md/
        # verify.yaml），并与用户重启后重新触发的下一轮起草并发写同一文件。
        # 退出链显式 killpg(SIGKILL) 整组终止（killpg 先例：core/knowledge.py
        # _kill_process_group）。惰性导入 + 吞异常：收割失败不得阻断下方
        # session/watcher/socket 收尾。
        try:
            from .routes.architecture_routes import _MANAGER as _arch_manager

            _arch_manager.reap_all()
        except Exception:  # noqa: BLE001
            pass
        try:
            from .routes.regression_routes import reap_all_autodraft

            reap_all_autodraft()
        except Exception:  # noqa: BLE001
            pass
        # dashboard-live-session 3.3：先终止会话子进程，再停 watcher。
        # code-review item 7ead46b03f0e：三步各自吞异常并留痕——任一项抛出不得
        # 跳过后续清理（server_close 被跳过会泄漏已绑定监听 socket，shutdown 被
        # 跳过会孤儿化 live-session 子进程），与上方启动段异常路径的逐项清理
        # 纪律对齐，保证 server_close 无条件执行。
        if httpd.session_manager is not None:
            try:
                httpd.session_manager.shutdown()
            except Exception as e:
                sys.stderr.write(f"dashboard 退出清理 session_manager 失败: {e}\n")
            httpd.session_manager = None
        try:
            watcher.stop()
        except Exception as e:
            sys.stderr.write(f"dashboard 退出清理 watcher 失败: {e}\n")
        try:
            httpd.server_close()
        except Exception as e:
            sys.stderr.write(f"dashboard 退出清理 server_close 失败: {e}\n")


def _is_process_alive(pid: int) -> bool:
    """进程是否存活（/proc/<pid> 目录存在即视为存活，Linux 限定）。"""
    try:
        return Path(f"/proc/{pid}").exists()
    except OSError:
        return False


def _proc_state(pid: int) -> str | None:
    """读 /proc/<pid>/stat 的 state 字段（第 3 字段，Z=僵尸）；读不到 → None。

    解析纪律同 _proc_starttime——comm 字段可能含空格/括号，从最后一个 ')'
    之后取字段，其后首字段即 state。仅用于接管等待期识别僵尸态旧实例。
    """
    try:
        data = Path(f"/proc/{pid}/stat").read_text()
        return data[data.rindex(")") + 2 :].split()[0]
    except (OSError, ValueError, IndexError):
        return None

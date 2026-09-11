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
    POST /api/spec-budget?project=<name>&spec=<name> → 设置/清除 per-spec 实现尝试预算覆盖（body: {"budget": 1-10 整数|null}，缺键/非法 400 / 终态 403）
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
import json
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

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# 帮助文档目录：core/dashboard/ 上两级 = 框架根（add-dashboard-help-center D2）
FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
HELP_DOCS_DIR = FRAMEWORK_ROOT / "docs" / "help"
# 文档名白名单（add-dashboard-help-center D2）：限定字母/数字/._- + .md，
# 从根上拒绝路径穿越片段；配合 real path 归属校验双保险
HELP_DOC_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.md$")

# 连接上限（dashboard-connection-limit D6，模块常量供测试 monkeypatch）
MAX_SSE_CONNECTIONS = 32    # SSE 活跃连接上限，超出拒绝新连接（客户端退化为轮询）
MAX_SERVER_THREADS = 64     # ThreadingHTTPServer 并发处理线程上限，超限 503
# SSE 客户端断开探测轮询间隔（秒）：队列空时每次等待该时长后探测 FIN。
# 心跳仍按 25s 发送；该间隔仅决定「释放连接槽位」的响应速度。
SSE_CLIENT_POLL_INTERVAL = 1.0


class SSEConnection:
    """一条浏览器 SSE 长连接：自带事件队列 + 该连接订阅的 run。

    慢客户端不阻塞广播者：队列满则丢弃最旧事件，队列上限防止内存无界增长。
    """

    def __init__(self, cid: str):
        self.id = cid
        self.queue = queue.Queue(maxsize=256)
        self.watched_runs = set()  # 该连接打开的 run 弹窗（增量推送目标）

    def send(self, event: dict):
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            pass


class SSEHub:
    """SSE 连接注册 / 广播 / run 订阅管理（供 watcher 推送 + handler 注册）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._conns = {}   # cid -> SSEConnection
        self._seq = 0

    def register(self) -> SSEConnection | None:
        """注册新 SSE 连接；活跃连接数 ≥ MAX_SSE_CONNECTIONS 时拒绝（返回 None）。

        拒绝语义（dashboard-connection-limit D6）：已建立连接不受影响；被拒客户端
        由前端退化为轮询（心跳兜底）。计数经锁保护，断开时 unregister 回落。
        """
        with self._lock:
            if len(self._conns) >= MAX_SSE_CONNECTIONS:
                return None
            self._seq += 1
            conn = SSEConnection(f"c{self._seq}")
            self._conns[conn.id] = conn
        return conn

    def unregister(self, conn: SSEConnection):
        with self._lock:
            self._conns.pop(conn.id, None)

    def broadcast(self, event: dict, run_id: str | None = None):
        """广播事件；run_id 非空时只发给订阅了该 run 的连接。"""
        with self._lock:
            conns = list(self._conns.values())
        for conn in conns:
            if run_id is None or run_id in conn.watched_runs:
                conn.send(event)

    def watch(self, cid: str, run_id: str):
        with self._lock:
            conn = self._conns.get(cid)
            if conn:
                conn.watched_runs.add(run_id)

    def unwatch(self, cid: str, run_id: str):
        with self._lock:
            conn = self._conns.get(cid)
            if conn:
                conn.watched_runs.discard(run_id)

    def is_watched(self, run_id: str) -> bool:
        with self._lock:
            return any(run_id in c.watched_runs for c in self._conns.values())


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


class DashboardHTTPServer(ThreadingHTTPServer):
    """携带 registry / static_dir / 项目缓存的自定义 HTTP 服务器。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, registry: Registry, static_dir: Path):
        super().__init__(addr, DashboardHandler)
        self.registry = registry
        self.static_dir = Path(static_dir)
        self.sse_hub = SSEHub()
        self.summary_index = dashboard_data.SummaryIndex()  # 摘要索引（thread-safe）
        self.watcher = None  # serve() 中创建并启动
        self._projects_cache = []
        self._cache_ts = 0.0
        self._cache_ttl = 10.0
        # 并发请求槽位计数（dashboard-connection-limit D6）：entry 获取、finally 释放
        self._request_slots = 0
        self._slots_lock = threading.Lock()

    def _try_acquire_request_slot(self) -> bool:
        """尝试获取一个处理槽位；并发数 ≥ MAX_SERVER_THREADS 时拒绝。"""
        with self._slots_lock:
            if self._request_slots >= MAX_SERVER_THREADS:
                return False
            self._request_slots += 1
            return True

    def _release_request_slot(self):
        with self._slots_lock:
            self._request_slots = max(0, self._request_slots - 1)

    def projects(self) -> list:
        """带 TTL 的发现结果缓存（扫描开销低但避免每次请求都扫盘）。"""
        now = time.time()
        if now - self._cache_ts > self._cache_ttl:
            self._projects_cache = self.registry.discover()
            self._cache_ts = now
        return self._projects_cache

    def project_by_name(self, name: str):
        for p in self.projects():
            if p["name"] == name:
                return p
        return None


# POST 请求体最大字节数（256KB，避免大内存占用）
MAX_POST_BODY = 256 * 1024


class DashboardHandler(BaseHTTPRequestHandler):
    """处理 GET/HEAD/POST/DELETE 请求，输出 JSON 或静态资源。

    protocol_version=HTTP/1.1：SSE 需要 keep-alive 长连接 + chunked 传输
    （普通响应均带 Content-Length，不受影响）。
    """

    server: DashboardHTTPServer  # 类型标注，便于 IDE

    protocol_version = "HTTP/1.1"

    # ── 基础 ─────────────────────────────────────────────────

    def do_GET(self):
        self._handle(method="GET")

    def do_HEAD(self):
        self._handle(method="HEAD")

    def do_POST(self):
        self._handle(method="POST")

    def do_DELETE(self):
        self._handle(method="DELETE")

    def log_message(self, fmt, *args):
        # 静默访问日志，避免污染运行终端
        pass

    def _handle(self, method: str = "GET"):
        # 线程上限（dashboard-connection-limit D6）：并发处理请求数超限时直接 503，
        # 不排队不堆积（防标签页风暴耗尽资源）。SSE 长连接本身占用线程，计数
        # 覆盖所有请求（含 /api/stream），上限需容纳常规 API + SSE 混合负载。
        if not self.server._try_acquire_request_slot():
            self._error(503, "server busy")
            return
        try:
            self._handle_inner(method)
        finally:
            self.server._release_request_slot()

    def _handle_inner(self, method: str = "GET"):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            if path.startswith("/api/"):
                if path == "/api/stream":
                    if method == "GET":
                        self._handle_sse()
                        return
                    self._error(405, "Method Not Allowed")
                    return
                if method == "POST":
                    self._handle_api_post(path, query)
                elif method == "DELETE":
                    self._handle_api_delete(path, query)
                else:
                    self._handle_api(path, query)
                return

            if method != "GET" and method != "HEAD":
                self._error(405, "Method Not Allowed")
                return

            if path == "/" or path == "/index.html":
                self._serve_static("dist/index.html")
            elif path.startswith("/screenshots/"):
                self._serve_screenshot(path)
            else:
                # 其它静态资源（dist/* 等）；_serve_static 内含防穿越校验
                self._serve_static(path.lstrip("/"))
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001 兜底：绝不让请求崩溃进程
            try:
                self._error(500, f"Internal Server Error: {e}")
            except Exception:
                pass

    def _handle_api(self, path: str, query: dict):
        if path == "/api/projects":
            self._json(self._api_projects())
        elif path == "/api/overview":
            self._json(self._api_overview())
        elif path == "/api/specs":
            self._json(self._api_specs(query))
        elif path.startswith("/api/specs/"):
            spec = urllib.parse.unquote(path[len("/api/specs/"):])
            self._json(self._api_spec_detail(spec, query))
        elif path.startswith("/api/runs/"):
            rest = urllib.parse.unquote(path[len("/api/runs/"):])
            if rest.endswith("/watch"):
                self._json(self._api_run_watch(rest[: -len("/watch")], query, watch=True))
            else:
                self._json(self._api_run(rest, query))
        elif path == "/api/events":
            self._json(self._api_events(query))
        elif path == "/api/alerts":
            self._json(self._api_alerts(query))
        elif path == "/api/admin-activities":
            self._json(self._api_admin_activities(query))
        elif path == "/api/config":
            self._json(self._api_config_get(query))
        elif path == "/api/hooks/audit":
            self._json(self._api_hooks_audit(query))
        elif path == "/api/prompts":
            self._json(self._api_prompts_get(query))
        elif path == "/api/todo":
            self._api_todo_get(query)
        elif path == "/api/verify-yaml":
            self._api_verify_yaml_get(query)
        elif path == "/api/verify-yaml-template":
            self._api_verify_yaml_template()
        elif path == "/api/spec-doc":
            self._json(self._api_spec_doc(query))
        elif path == "/api/help/docs":
            self._json(self._api_help_docs())
        elif path == "/api/help/doc":
            self._api_help_doc(query)
        else:
            self._error(404, "Not Found")

    # ── API 实现 ─────────────────────────────────────────────

    def _api_projects(self) -> dict:
        projects = []
        for p in self.server.projects():
            if not p.get("exists"):
                projects.append({
                    "name": p["name"], "path": p["path"],
                    "discovered": p.get("discovered", False),
                    "exists": False, "daemon": "stopped", "error": "项目路径不存在",
                })
                continue
            s = dashboard_data.project_summary(p["path"], p["name"], p["path"])
            s["discovered"] = p.get("discovered", False)
            s["exists"] = True
            projects.append(s)
        return {"projects": projects}

    def _api_overview(self) -> dict:
        return dashboard_data.overview(self.server.projects())

    def _api_specs(self, query) -> dict:
        project = self._project_from_query(query)
        if project is None:
            return {"error": "unknown project", "specs": []}
        if not project.get("exists"):
            return {"error": "project not found", "specs": []}
        proot = Path(project["path"])
        items = self.server.summary_index.get(proot)
        items.sort(key=lambda s: s.get("created") or "", reverse=True)
        return {"project": project["name"], "specs": items}

    def _api_spec_detail(self, spec: str, query) -> dict:
        project = self._project_from_query(query)
        if project is None:
            return {"error": "unknown project"}
        if not project.get("exists"):
            return {"error": "project not found"}
        proot = Path(project["path"])
        specs = dashboard_data.parse_state(proot)
        entry = specs.get(spec)
        if entry is None:
            return {"error": f"spec not found: {spec}", "project": project["name"]}
        detail = dashboard_data.spec_detail(proot, spec, entry)
        detail["project"] = project["name"]
        return detail

    def _api_spec_doc(self, query) -> dict:
        """GET /api/spec-doc?project=<name>&spec=<name>&doc=<proposal|design|tasks>

        读取 SPEC 的 proposal.md / design.md / tasks.md 原文返回 {found, content}。
        - doc 非法 → 400
        - spec 非法 / 不在项目 STATE.md → 404（且不读取任何 changes 目录外文件）
        - 文件不存在 → 200 + {found: false, content: ""}
        """
        doc = query.get("doc", [None])[0]
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(400, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        # 文件缺失是常态分支，但 spec 必须真在项目 STATE.md 中（D2：仅未知 spec 才 404）
        proot = Path(project["path"])
        specs = dashboard_data.parse_state(proot)
        if spec not in specs:
            self._error(404, f"spec not found: {spec}")
            return
        try:
            result = dashboard_data.get_spec_doc(proot, spec, doc)
        except dashboard_data.InvalidSpecDoc:
            self._error(400, f"invalid doc: {doc}")
            return
        except dashboard_data.InvalidSpecName:
            self._error(404, f"invalid spec: {spec}")
            return
        self._json({**result, "project": project["name"], "spec": spec, "doc": doc})

    # ── 帮助文档（add-dashboard-help-center D1/D2）─────────────────────

    @staticmethod
    def _help_doc_title(content: str) -> str:
        """从 Markdown 原文解析首个一级标题（# 行）作为文档标题。

        无一级标题时回退为去后缀文件名，保证清单端点始终有可展示标题。
        """
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                return stripped[2:].strip() or ""
        return ""

    def _api_help_docs(self) -> dict:
        """GET /api/help/docs

        列出框架仓库 docs/help/ 下全部合法 .md 文档，返回 [{name, title}]。
        - README.md 置顶（默认文档），其余按文件名字典序（NN- 编号天然有序）
        - 目录缺失 / 为空 → 空列表（前端空态）
        - 非 .md 文件跳过不计入清单
        """
        help_dir = HELP_DOCS_DIR.resolve()
        if not help_dir.is_dir():
            return {"docs": []}
        try:
            files = sorted(p for p in help_dir.iterdir()
                           if p.is_file() and HELP_DOC_NAME_RE.match(p.name))
        except OSError:
            return {"docs": []}
        docs = []
        try:
            for f in files:
                title = ""
                try:
                    title = self._help_doc_title(
                        f.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    title = ""
                docs.append({"name": f.name, "title": title or f.name[:-3]})
        except OSError:
            return {"docs": []}
        # README 置顶（设计 D5：文件名即路由参数，README 为默认文档）
        docs.sort(key=lambda d: (d["name"] != "README.md", d["name"]))
        return {"docs": docs}

    def _api_help_doc(self, query):
        """GET /api/help/doc?name=<file>

        返回单篇帮助文档 Markdown 原文 {name, content, title}。
        - 名字不匹配白名单（[A-Za-z0-9._-]+\.md）→ 400（防穿越，不泄露信息）
        - 解析后 real path 不在 docs/help/ 内 → 400
        - 目录缺失 / 文件不存在 → 404
        """
        name = query.get("name", [None])[0] or ""
        if not name or not HELP_DOC_NAME_RE.match(name):
            self._error(400, "invalid help doc name")
            return
        help_dir = HELP_DOCS_DIR.resolve()
        target = (help_dir / name).resolve()
        # 防穿越：解析后必须仍位于 docs/help/ 内（dirs 缺省，不会跑到 docs 其它处）
        if not target.is_relative_to(help_dir):
            self._error(400, "invalid help doc name")
            return
        if not target.is_file():
            self._error(404, "help doc not found")
            return
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self._error(404, "help doc not found")
            return
        self._json({
            "name": name,
            "title": self._help_doc_title(content) or name[:-3],
            "content": content,
        })

    def _api_spec_error_clear(self, query) -> dict:
        """POST /api/spec-error-clear?project=<name>&spec=<name>

        在线清除 SPEC 的 error 字段（置空并原子写回 STATE.md）。
        - project 不存在 → 404
        - spec 非法 / 不在项目 STATE.md → 404
        - 成功 → 200 + {ok: true}；其余字段不受影响
        - 写回异常 → 500
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.clear_spec_error(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            self._error(500, f"clear spec error failed: {e}")
            return
        if not result.get("found"):
            self._error(404, f"spec not found: {spec}")
            return
        self._json({"ok": True, "project": project["name"], "spec": spec})

    def _api_spec_priority(self, query):
        """POST /api/spec-priority?project=<name>&spec=<name>  body: {"priority": N}

        设置 SPEC 优先级（1-9，P1 最高）。
        - project 不存在 → 404
        - spec 不在项目 STATE.md → 404
        - body 缺 priority / 非法值（0、10、非整数）→ 400
        - 成功 → 200 + {ok: true, priority: N}
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        body = self._read_json_body()
        if body is None:
            return
        if "priority" not in body:
            self._error(400, "priority required in request body")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.set_spec_priority(proot, spec, body["priority"])
        except dashboard_data.InvalidPriority:
            self._error(400, "priority must be an integer between 1 and 9")
            return
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            self._error(500, f"set spec priority failed: {e}")
            return
        if not result.get("found"):
            self._error(404, f"spec not found: {spec}")
            return
        self._json({"ok": True, "project": project["name"], "spec": spec,
                    "priority": result["priority"]})

    def _api_spec_freeze(self, query) -> dict:
        """POST /api/spec-freeze?project=<name>&spec=<name>

        人工冻结 SPEC：status→blocked，error 以「用户指令冻结：」开头
        （admin_monitor 认此模式为有意等待态，免超时误报）。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - 终态（done/pushed）→ 200 + {ok: true, frozen: false, error: 原因}
        - 成功 → 200 + {ok: true, frozen: true}
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        result = dashboard_data.freeze_spec(Path(project["path"]), spec)
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        self._json(result)

    def _api_spec_unfreeze(self, query) -> dict:
        """POST /api/spec-unfreeze?project=<name>&spec=<name>

        解冻 SPEC：恢复冻结前状态并清空 error；未冻结为幂等 no-op。
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        result = dashboard_data.unfreeze_spec(Path(project["path"]), spec)
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        self._json(result)

    def _api_spec_start_after(self, query) -> dict:
        """POST /api/spec-start-after?project=<name>&spec=<name>
        body: {"value": "<iso-utc>"|null}

        设置/清除 SPEC 定时拾取时间（start_after，ISO8601 UTC；null 即清除）。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - 终态（done/pushed）→ 403「终态不可设置定时拾取」
        - value 非法 ISO8601 → 400（STATE.md 不变）
        - 成功 → 200 + {ok: true, start_after: <iso|null>}
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        body = self._read_json_body()
        if body is None:
            return
        if "value" not in body:
            self._error(400, "value required in request body (ISO8601 UTC or null)")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.set_spec_start_after(proot, spec, body["value"])
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            self._error(500, f"set spec start_after failed: {e}")
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        if result.get("terminal"):
            self._error(403, result.get("error") or "终态不可设置定时拾取")
            return
        if result.get("invalid"):
            self._error(400, result.get("error") or "start_after 非法 ISO8601")
            return
        self._json({"ok": True, "project": project["name"], "spec": spec,
                    "start_after": result.get("start_after")})

    def _api_spec_freeze_config(self, query) -> dict:
        """POST /api/spec-freeze-config?project=<name>&spec=<name>
        body: {"mode": "permanent"|"scheduled"|"unfreeze", "until": "<iso-utc>"?}

        冻结管理配置：永久 ↔ 定时解冻 ↔ 立即解冻。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - spec 未处于冻结态 → 409「冻结管理仅对冻结 spec 生效」
        - mode 非法 / scheduled 的 until 非法 ISO8601 → 400
        - 成功 → 200 + {ok: true, mode, frozen_until, unfrozen?}
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        body = self._read_json_body()
        if body is None:
            return
        if "mode" not in body:
            self._error(400, "mode required in request body")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.configure_spec_freeze(
                proot, spec, body["mode"], body.get("until"))
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            self._error(500, f"configure spec freeze failed: {e}")
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        if result.get("invalid"):
            self._error(400, result.get("error") or "非法请求")
            return
        if result.get("error") and not result.get("ok"):
            self._error(409, result.get("error"))
            return
        self._json({
            "ok": True, "project": project["name"], "spec": spec,
            "mode": result.get("mode"),
            "frozen_until": result.get("frozen_until"),
            "unfrozen": result.get("unfrozen", False),
        })

    def _api_spec_budget(self, query) -> dict:
        """POST /api/spec-budget?project=<name>&spec=<name>
        body: {"budget": <1-10 整数|null>}

        设置/清除 SPEC 的实现尝试预算覆盖（impl_run_budget_override）。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - body 缺 budget 键 / 非整数（bool/浮点/字符串数字）→ 400
        - 越界（0、11）→ 400
        - 终态（done/pushed）→ 403「终态不可设置预算覆盖」
        - 成功 → 200 + {ok: true, budget: <值|null>}（null 清除覆盖，恢复跟随全局）
        修改只写覆盖属性，不触碰 _impl_run_budget_used（对账组件管辖）。
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        body = self._read_json_body()
        if body is None:
            return
        if "budget" not in body:
            self._error(400, "budget required in request body (1-10 int or null)")
            return
        budget = body["budget"]
        # 非整数（含 bool、浮点、字符串数字）拒绝——null 合法（清除覆盖）
        if budget is not None and (
            isinstance(budget, bool) or not isinstance(budget, int)
        ):
            self._error(400, "budget must be an integer between 1 and 10 (or null to clear)")
            return
        if budget is not None and (budget < 1 or budget > 10):
            self._error(400, "budget must be an integer between 1 and 10 (or null to clear)")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.set_spec_budget(proot, spec, budget)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            self._error(500, f"set spec budget failed: {e}")
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        if result.get("terminal"):
            self._error(403, result.get("error") or "终态不可设置预算覆盖")
            return
        if result.get("invalid"):
            self._error(400, result.get("error") or "budget must be an integer between 1 and 10 (or null to clear)")
            return
        self._json({"ok": True, "project": project["name"], "spec": spec,
                    "budget": result.get("budget")})

    def _api_spec_archive(self, query) -> dict:
        """POST /api/spec-archive?project=<name>&spec=<name>

        归档终态 SPEC：把 spec/changes/<name>/ 移到 archive/YYYY-MM-DD-<name>/，
        STATE.md 条目原样保留（与 fenix_archive.py / fenix-archive skill 同语义）。
        - project 不存在 → 404
        - spec 不在 STATE.md → 404
        - 非终态（非 done/pushed）→ 403「仅终态可归档」
        - 目标已存在 → 409（不覆盖）
        - 已归档（活跃目录缺失）→ 409「已归档」
        - 成功 → 200 + {ok: true, from, to} + 记录项目活动事件（from→to）
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.archive_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：移动异常不崩溃进程
            self._error(500, f"archive spec failed: {e}")
            return
        if not result.get("found"):
            self._error(404, result.get("error") or f"spec not found: {spec}")
            return
        if not result.get("ok"):
            # 已归档或目标冲突 → 409，非终态拒绝也走这里（调用方可识别具体 error）
            code = 409 if "已存在" in (result.get("error") or "") or "已归档" in (result.get("error") or "") else 403
            self._error(code, result.get("error") or "归档失败")
            return
        # 归档成功 → 记录项目活动事件（归档动作 from→to，供活动页/概览展示）
        try:
            dashboard_data.record_project_event(
                proot,
                "dashboard",
                f"Spec '{spec}' 已归档: {result['from']} → {result['to']}",
                context={"spec": spec, "from": result["from"], "to": result["to"]},
            )
        except Exception:
            pass  # 写日志失败不阻断归档响应
        resp = {"ok": True, "project": project["name"], "spec": spec,
                "from": result["from"], "to": result["to"],
                "committed": result.get("committed", False)}
        if result.get("commit_warning"):
            resp["commit_warning"] = result["commit_warning"]
        self._json(resp)

    def _api_spec_promote(self, query) -> dict:
        """POST /api/spec-promote?project=<name>&spec=<name>

        人工晋升 drafted SPEC：调用共享晋升函数（软化+lint+transition ready）。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - 非 drafted → 200 + {ok: false, reason: ...}
        - lint 违规 → 200 + {ok: false, violations: [...]}
        - 成功 → 200 + {ok: true}
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.promote_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：晋升异常不崩溃进程
            self._error(500, f"promote spec failed: {e}")
            return
        if not result.get("found"):
            self._error(404, result.get("error") or f"spec not found: {spec}")
            return
        self._json(result)

    def _api_spec_approve_push(self, query):
        """POST /api/spec-approve-push?project=<name>&spec=<name>

        审批推送 done SPEC：写入 .fenix/approve_push_request.json 文件信号，
        由 daemon 主循环下一轮（≤2s）拾取并调 pm_engine.approve_push 执行推送。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - daemon 未运行 → 409「daemon 未运行，请先启动 daemon」（信号无人消费）
        - 已有未消费信号 → 409「已有进行中的审批推送请求」
        - spec 非 done → 403（pushed 幂等无操作、其他状态非法，error 区分）
        - 成功 → 200 + {ok: true, project, spec, created}
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.request_spec_approve_push(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写文件异常不崩溃进程
            self._error(500, f"spec approve push request failed: {e}")
            return
        if not result.get("found"):
            self._error(404, result.get("error") or f"spec not found: {spec}")
            return
        if result.get("daemon_down"):
            self._error(409, result.get("error") or "daemon 未运行，请先启动 daemon")
            return
        if result.get("conflict"):
            self._error(409, result.get("error") or "已有进行中的审批推送请求")
            return
        if result.get("terminal"):
            self._error(403, result.get("error") or "仅 done 状态可审批推送")
            return
        self._json({"ok": True, "project": project["name"], "spec": spec,
                    "created": result.get("created")})

    def _api_spec_delete(self, query):
        """POST /api/spec-delete?project=<name>&spec=<name>

        软删除 SPEC：STATE.md 移除条目 + SPEC 目录移入 spec/archive。
        - project 不存在 → 404
        - spec 不在项目 STATE.md → 404（幂等，不发文件操作）
        - spec 有进行中的运行（runs 目录 mtime<120s）→ 409「spec 有进行中的运行」
        - 成功 → 200 + {ok: true, archived, archive_path}
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.soft_delete_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写回/移动异常不崩溃进程
            self._error(500, f"delete spec failed: {e}")
            return
        if not result.get("found"):
            self._error(404, f"spec not found: {spec}")
            return
        if result.get("running"):
            self._error(409, result.get("error") or "spec 有进行中的运行")
            return
        self._json({"ok": True, "project": project["name"], "spec": spec,
                    "archived": result.get("archived", False),
                    "archive_path": result.get("archive_path")})

    def _api_spec_admin_invoke(self, query):
        """POST /api/spec-admin-invoke?project=<name>&spec=<name>

        手动唤起 Administrator：写入 .fenix/admin_invoke_request.json 文件信号，
        由 daemon 主循环下一轮扫描拾取并唤起。
        - project 不存在 → 404
        - spec 不在项目 STATE.md → 404
        - 已有未消费请求（进行中处置）→ 409「已有进行中的 Admin 处置」
        - 成功 → 200 + {ok: true, created}
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        # 用户提示词（可选，POST JSON body {prompt}）：v1 客户端不带 body 仍兼容
        prompt = None
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            content_length = 0
        if content_length > 0:
            body = self._read_json_body()
            if isinstance(body, dict):
                prompt = (body.get("prompt") or "").strip() or None
        proot = Path(project["path"])
        try:
            result = dashboard_data.request_admin_invoke(proot, spec, prompt)
        except Exception as e:  # noqa: BLE001 兜底：写文件异常不崩溃进程
            self._error(500, f"admin invoke request failed: {e}")
            return
        if not result.get("found"):
            self._error(404, result.get("error") or f"spec not found: {spec}")
            return
        if result.get("conflict"):
            self._error(409, result.get("error") or "已有进行中的 Admin 处置")
            return
        self._json({"ok": True, "project": project["name"], "spec": spec,
                    "created": result.get("created")})

    def _api_run_cancel(self, query):
        """POST /api/run-cancel?project=<name>&run_id=<id>（可选 reason）

        run 人工取消：写入 .fenix/cancel_run_request.json 文件信号，由 daemon
        主循环下一轮拾取并调 agent_runner.cancel_run。
        - project 不存在 → 404
        - run_id 缺失 → 400
        - 已有未消费请求 → 409
        - 受理 → 200 + {"requested": true}
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        run_id = query.get("run_id", [None])[0]
        if not run_id or not run_id.strip():
            self._error(400, "run_id required")
            return
        # 可选 reason（POST JSON body {reason} 或 query 参数）
        reason = query.get("reason", [None])[0]
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            content_length = 0
        if content_length > 0 and (reason is None or not reason):
            body = self._read_json_body()
            if isinstance(body, dict):
                reason = (body.get("reason") or "").strip() or None
        reason = (reason or "").strip() or "" if reason is not None else ""

        proot = Path(project["path"])
        try:
            result = dashboard_data.request_run_cancel(proot, run_id, reason)
        except Exception as e:  # noqa: BLE001 兜底：写文件异常不崩溃进程
            self._error(500, f"run cancel request failed: {e}")
            return
        if result.get("missing_run_id"):
            self._error(400, "run_id required")
            return
        if result.get("conflict"):
            self._error(409, result.get("error") or "已有进行中的取消请求")
            return
        self._json({"requested": True, "project": project["name"],
                    "run_id": run_id, "created": result.get("created")})

    def _api_run(self, run_id: str, query) -> dict:
        project = self._project_from_query(query)
        if project is None:
            return {"error": "unknown project"}
        if not project.get("exists"):
            return {"error": "project not found"}
        try:
            tail = min(int(query.get("tail", ["300"])[0]), 2000)
        except (TypeError, ValueError):
            tail = 300
        run = dashboard_data.get_run_events(Path(project["path"]), run_id, tail=tail)
        run["project"] = project["name"]
        return run

    def _api_run_watch(self, run_id: str, query, watch: bool) -> dict:
        """注册/取消某条 SSE 连接的 run 增量订阅（弹窗打开/关闭时调用）。"""
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            return {"error": "unknown project"}
        cid = query.get("cid", [None])[0]
        if not cid:
            return {"error": "missing cid"}
        if watch:
            self.server.sse_hub.watch(cid, run_id)
        else:
            self.server.sse_hub.unwatch(cid, run_id)
        return {"ok": True}

    def _api_events(self, query) -> dict:
        project = self._project_from_query(query)
        if project is None:
            return {"events": []}
        if not project.get("exists"):
            return {"events": []}
        try:
            minutes = int(query.get("minutes", ["10"])[0])
        except ValueError:
            minutes = 10
        events = dashboard_data.get_recent_events(Path(project["path"]), minutes=minutes)
        return {"project": project["name"], "events": events}

    def _api_config_get(self, query) -> dict:
        project = self._project_from_query(query)
        if project is None:
            # 无项目 → 用户级配置（scope=user，不再返回 unknown project）
            return dashboard_data.read_config(None, scope="user")
        if not project.get("exists"):
            return {"error": "project not found"}
        config = dashboard_data.read_effective_config(project["path"])
        config["project"] = project["name"]
        return config

    def _api_hooks_audit(self, query) -> dict:
        """GET /api/hooks/audit?project=<name>&spec=<name>&limit=20 — hook 审计记录查询。

        - 项目缺失/不存在 → 空列表（用户级作用域无 hook 审计文件）
        - spec 可选过滤（事件按 spec 记审计）；limit 默认 20，夹取 [1, 200]
        - 读取 .fenix/hook_audit.jsonl 尾部，时间倒序（read_hook_audit 纯函数）
        """
        from core.hook_engine import read_hook_audit
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            return {"project": None, "audit": []}
        spec = query.get("spec", [None])[0]
        try:
            limit = max(1, min(200, int(query.get("limit", ["20"])[0])))
        except (TypeError, ValueError):
            limit = 20
        records = read_hook_audit(
            Path(project["path"]), spec=(spec or None), limit=limit
        )
        return {"project": project["name"], "audit": records}

    # ── agent 提示词（add-agent-prompt-files 任务 3.1）────────────────

    def _api_prompts_get(self, query) -> dict:
        """GET /api/prompts[?project=<name>] — agent 提示词读取。

        缺省 → 仅通用层六文件（用户级只读视图）；带 project → 追加项目级
        .fenix/agents/ 附加内容。通用层一律只读，端点不提供通用层写入。
        """
        agents = []
        for atype, fname in AGENT_PROMPT_FILES.items():
            path = AGENT_PROMPT_DIR / fname
            try:
                content = path.read_text(encoding="utf-8") if path.is_file() else ""
            except OSError:
                content = ""
            agents.append({"type": atype, "file": fname, "content": content})
        out: dict = {"agents": agents}
        project = self._project_from_query(query)
        if project is None:
            return out
        if not project.get("exists"):
            return {"error": "project not found"}
        proot = Path(project["path"])
        out["project"] = {
            "name": project["name"],
            "path": project["path"],
            # 所有项目一视同仁（含 fenixd 自身）；仅废弃软链布局 extras 为空串
            "extras": {
                atype: self._read_project_extra(proot, atype)
                for atype in AGENT_PROMPT_FILES
            },
        }
        return out

    @staticmethod
    def _read_project_extra(proot: Path, agent_type: str) -> str:
        agents_dir = project_agents_dir(proot)
        if agents_dir is None:
            return ""
        path = agents_dir / AGENT_PROMPT_FILES[agent_type]
        if not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _api_prompts_post(self, query):
        """POST /api/prompts?project=<name> — 保存项目附加提示词。

        body: {"agent_type": <白名单键>, "content": <自由 Markdown>}。
        写入 <项目根>/.fenix/agents/<agent-type>.md（该目录唯一写入口，
        框架运行时代码不写项目级目录）；.fenix/agents 解析为通用层目录的
        废弃软链布局拒绝（403，项目通道永不触碰通用层）。
        """
        body = self._read_json_body()
        if body is None:
            return
        name = query.get("project", [None])[0]
        if not name:
            self._error(400, "缺少 project 参数（项目附加提示词必须挂到具体项目）")
            return
        project = self.server.project_by_name(name)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        agent_type = body.get("agent_type")
        if not isinstance(agent_type, str) or agent_type not in AGENT_PROMPT_FILES:
            self._error(400, f"非法 agent_type（白名单外）: {agent_type}")
            return
        proot = Path(project["path"])
        agents_dir = project_agents_dir(proot)
        if agents_dir is None:
            self._error(
                403,
                "项目 .fenix/agents 解析为框架通用层 agents/（废弃自引用软链布局），"
                "项目通道禁止写入通用提示词",
            )
            return
        content = body.get("content")
        if not isinstance(content, str):
            self._error(400, "content 必须为字符串（自由 Markdown，不做 schema 校验）")
            return
        target = agents_dir / AGENT_PROMPT_FILES[agent_type]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._json({"ok": True, "agent_type": agent_type, "path": str(target)})

    def _project_query_or_error(self, query, what: str):
        """文件级项目端点共用校验：缺 project 400、项目未知/不存在 404。

        通过返回项目 dict；失败已发送错误响应并返回 None。
        """
        name = query.get("project", [None])[0]
        if not name:
            self._error(400, f"缺少 project 参数（{what}为项目级文件）")
            return None
        project = self.server.project_by_name(name)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return None
        return project

    def _api_todo_get(self, query) -> None:
        """GET /api/todo?project=<name> — 项目 todo.md 读取（设置页「自省」面板）。

        路径固定为 <项目根>/.fenix/todo.md，不接受任意路径参数。
        文件尚不存在（自省未运行过）返回空串 + exists=false。
        """
        project = self._project_query_or_error(query, "todo.md")
        if project is None:
            return
        proot = Path(project["path"])
        target = proot / ".fenix" / "todo.md"
        exists = target.is_file()
        content = ""
        try:
            if exists:
                content = target.read_text(encoding="utf-8")
        except OSError as e:
            self._error(500, f"todo.md 读取失败: {e}")
            return
        self._json({"project": project["name"], "path": str(target),
                    "exists": exists, "content": content})

    def _api_todo_post(self, query):
        """POST /api/todo?project=<name> — 保存项目 todo.md（整文件覆写）。

        body: {"content": <自由 Markdown>}。文件不存在时自动创建；
        daemon 自省会追加写入此文件，覆写保存以 UI 提交内容为准。
        """
        body = self._read_json_body()
        if body is None:
            return
        project = self._project_query_or_error(query, "todo.md")
        if project is None:
            return
        content = body.get("content")
        if not isinstance(content, str):
            self._error(400, "content 必须为字符串（自由 Markdown，不做 schema 校验）")
            return
        proot = Path(project["path"])
        target = proot / ".fenix" / "todo.md"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as e:
            self._error(500, f"todo.md 保存失败: {e}")
            return
        self._json({"ok": True, "project": project["name"], "path": str(target)})

    def _api_verify_yaml_get(self, query) -> None:
        """GET /api/verify-yaml?project=<name> — 验证契约文件读取（设置页「项目简介」面板）。

        路径固定为 <项目根>/.fenix/verify.yaml，不接受任意路径参数。
        文件尚不存在返回空串 + exists=false（前端提示可从模板创建）。
        """
        project = self._project_query_or_error(query, "verify.yaml")
        if project is None:
            return
        proot = Path(project["path"])
        target = proot / ".fenix" / "verify.yaml"
        exists = target.is_file()
        content = ""
        try:
            if exists:
                content = target.read_text(encoding="utf-8")
        except OSError as e:
            self._error(500, f"verify.yaml 读取失败: {e}")
            return
        self._json({"project": project["name"], "path": str(target),
                    "exists": exists, "content": content})

    def _api_verify_yaml_post(self, query):
        """POST /api/verify-yaml?project=<name> — 保存验证契约（整文件覆写）。

        body: {"content": <自由 YAML>}。与 todo.md 的关键差异：保存前做校验——
        1. YAML 语法必须可解析（坏 YAML 会被 load_verify_contract 按「无契约」
           静默回退，用户以为契约生效了实则没有，编辑器必须当场拦截）；
        2. 顶层必须为字段映射或空（列表/标量同样静默失效）。
        不做字段级 schema 校验：加载器对未知字段宽容，字段语义在模板注释里。
        """
        body = self._read_json_body()
        if body is None:
            return
        project = self._project_query_or_error(query, "verify.yaml")
        if project is None:
            return
        content = body.get("content")
        if not isinstance(content, str):
            self._error(400, "content 必须为字符串（自由 YAML，不做字段级 schema 校验）")
            return
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            self._error(400, f"YAML 语法错误，拒绝保存（坏契约会被框架按「无契约」"
                             f"静默回退）: {e}")
            return
        if data is not None and not isinstance(data, dict):
            self._error(400, f"verify.yaml 顶层必须是字段映射（prepare/serve/ready），"
                             f"当前为 {type(data).__name__}——非映射契约会被框架静默失效")
            return
        proot = Path(project["path"])
        target = proot / ".fenix" / "verify.yaml"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as e:
            self._error(500, f"verify.yaml 保存失败: {e}")
            return
        self._json({"ok": True, "project": project["name"], "path": str(target)})

    def _api_verify_yaml_template(self) -> None:
        """GET /api/verify-yaml-template — 契约模板原文（设置页「插入模板」按钮）。

        模板单一来源 = core/verify_contract_template.yaml（fenix-init 生成、
        setup skill 复制均引用同一文件）；全部配置行注释 = 惰性 YAML。
        """
        template = (Path(__file__).resolve().parent.parent
                    / "verify_contract_template.yaml")
        try:
            content = template.read_text(encoding="utf-8")
        except OSError as e:
            self._error(500, f"契约模板读取失败: {e}")
            return
        self._json({"path": str(template), "template": content})

    def _api_verify_yaml_autodraft_post(self, query: dict):
        """POST /api/verify-yaml-autodraft?project=<name> — 触发 AI 起草验证契约。

        项目解析复用现有 verify-yaml 端点路径（未知项目 404）；
        load_verify_contract 轻量判定——契约缺失/解析失败（contract is None）写
        verify_contract_missing SIGNAL；契约可解析且带覆盖确认（overwrite=true）改写
        verify_contract_redraft SIGNAL（fix-verify-contract-signal-semantics B：
        语义拆分，missing 回归纯缺失语义，覆盖重起草不再旁路 missing）。
        两者均为 AdminStore.append，source=ui-manual、overwrite 标记、spec 字段留空、
        项目名入 evidence，响应 dispatched；
        契约有效且无 overwrite 响应 skipped（附「契约已有效」文案）不写信号；
        写前在途去重（D2）：同项目同 signal_type 未消费信号已存在则不重复写，
        响应仍 dispatched 且 message 注明已有在途请求。
        """
        body = self._read_json_body()
        if body is None:
            return
        project = self._project_query_or_error(query, "verify-yaml-autodraft")
        if project is None:
            return
        proot = Path(project["path"])
        from core.verify_contract import load_verify_contract
        contract = load_verify_contract(proot, logger=None)
        overwrite = bool(body.get("overwrite"))
        if contract is not None and not overwrite:
            # 有效契约且无覆盖确认 → skipped
            self._json({
                "ok": True,
                "project": project["name"],
                "status": "skipped",
                "message": "契约已有效，无需自动起草。如需覆盖，请确认覆盖意图后重试。",
            })
            return
        # 契约缺失/解析失败 → verify_contract_missing；契约有效且带覆盖确认 → verify_contract_redraft
        signal_type = "verify_contract_missing" if contract is None else "verify_contract_redraft"
        store = AdminStore(proot, logger=None)
        evidence_detail = f"项目名={project['name']}"
        if overwrite:
            evidence_detail += "; 覆盖确认=是"
        # 在途去重（D2）：同项目同 signal_type 未消费信号已存在 → 不重复写。
        # 异类型互不抑制（missing 在途不挡 redraft——契约被修正后确认覆盖是新意图）；
        # 已 handled 的历史信号不抑制（用户可再次请求）。
        inflight = [
            r for r in store.read_all()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == signal_type
            and not r.get("handled")
            and f"项目名={project['name']}" in (r.get("evidence") or "")
        ]
        if inflight:
            self._json({
                "ok": True,
                "project": project["name"],
                "status": "dispatched",
                "message": "已有在途的验证契约处理请求，无需重复触发；Administrator 将在下一轮巡检拾取（数分钟内），结果见运维记录。",
            })
            return
        store.append({
            "kind": SIGNAL,
            "signal_type": signal_type,
            "spec": None,
            "severity": "major",
            "description": "AI 起草验证契约请求（UI 手动触发）",
            "evidence": evidence_detail,
            "source": "ui-manual",
            "overwrite": overwrite,
            "recommended_action": "Administrator 将在下一轮巡检拾取（数分钟内），结果见运维记录；完成后可点重新加载查看新契约。",
        })
        self._json({
            "ok": True,
            "project": project["name"],
            "status": "dispatched",
            "message": "已提交 AI 起草请求，Administrator 将在下一轮巡检拾取（数分钟内），结果见运维记录；完成后可点重新加载查看新契约。",
        })

    def _api_alerts(self, query) -> dict:
        """读取 Administrator 告警。

        ?project=<name> → 该项目全部告警/处置记录 + 摘要；
        缺省 → 跨项目聚合所有未处理升级告警（供顶部横幅），并附已解决
        告警（resolved，add-alert-auto-resolve D5 视图分组用）。
        """
        project_name = query.get("project", [None])[0]
        if project_name:
            project = self.server.project_by_name(project_name)
            if project is None or not project.get("exists"):
                return {"error": "project not found"}
            proot = Path(project["path"])
            return {
                "project": project["name"],
                "alerts": dashboard_data.get_alerts(proot),
                "summary": dashboard_data.alerts_summary(proot),
            }

        projects_out = []
        all_unhandled = []
        all_resolved = []
        total = 0
        for p in self.server.projects():
            if not p.get("exists"):
                continue
            proot = Path(p["path"])
            summary = dashboard_data.alerts_summary(proot)
            projects_out.append({"name": p["name"], **summary})
            total += summary["unhandled_count"]
            for a in dashboard_data.get_unhandled_alerts(proot):
                item = dict(a)
                item["project"] = p["name"]
                all_unhandled.append(item)
            # add-alert-auto-resolve D5：已解决告警随横幅 payload 下发，
            # 前端折叠为「已解决 (N)」区（按 handled_by 区分自动解决/人工处理）
            for a in dashboard_data.get_resolved_alerts(proot):
                item = dict(a)
                item["project"] = p["name"]
                all_resolved.append(item)
        all_unhandled.sort(key=lambda a: a.get("created", ""), reverse=True)
        all_resolved.sort(
            key=lambda a: a.get("handled_at") or a.get("created") or "",
            reverse=True)
        return {
            "total_unhandled": total,
            "projects": projects_out,
            "alerts": all_unhandled,
            "resolved": all_resolved,
        }

    def _api_admin_activities(self, query) -> dict:
        """读取 Administrator 活动记录（运维记录时间线）。

        ?project=<name> → 该项目全部处置活动（未处理升级关联置顶）；
        带 ?spec=<name> → 仅返回该 SPEC 相关记录（add-admin-invoke-dialog，
        服务端过滤）；缺省 → 跨项目聚合，按项目分组返回。
        """
        project_name = query.get("project", [None])[0]
        spec_name = query.get("spec", [None])[0]
        if project_name:
            project = self.server.project_by_name(project_name)
            if project is None or not project.get("exists"):
                return {"error": "project not found"}
            proot = Path(project["path"])
            return {
                "project": project["name"],
                "spec": spec_name or "",
                "activities": dashboard_data.get_admin_activities(
                    proot, spec=spec_name),
            }

        projects_out = []
        for p in self.server.projects():
            if not p.get("exists"):
                continue
            acts = dashboard_data.get_admin_activities(
                Path(p["path"]), spec=spec_name)
            for a in acts:
                a["project"] = p["name"]
            projects_out.append({"name": p["name"], "activities": acts})
        return {"projects": projects_out}

    def _api_alert_handled(self, alert_id: str, query) -> dict:
        """标记某条升级告警为已处理；成功后广播让前端横幅刷新。"""
        project = self._project_from_query(query)
        if project is None:
            self._error(400, "unknown project")
            return
        if not project.get("exists"):
            self._error(400, "project not found")
            return
        if not alert_id:
            self._error(400, "missing alert id")
            return
        if not dashboard_data.mark_alert_handled(Path(project["path"]), alert_id):
            self._error(404, "alert not found or already handled")
            return
        try:
            self.server.sse_hub.broadcast({
                "project": project["name"], "type": "alerts",
                "summary": dashboard_data.alerts_summary(Path(project["path"])),
            })
        except Exception:
            pass
        self._json({"ok": True, "id": alert_id})

    def _api_alerts_clear(self):
        """清理所有事件：把全部项目未处理升级告警标记为已处理；逐项目广播刷新横幅。"""
        cleared = 0
        for p in self.server.projects():
            if not p.get("exists"):
                continue
            proot = Path(p["path"])
            cleared += dashboard_data.mark_all_alerts_handled(proot)
            try:
                self.server.sse_hub.broadcast({
                    "project": p["name"], "type": "alerts",
                    "summary": dashboard_data.alerts_summary(proot),
                })
            except Exception:
                pass
        self._json({"ok": True, "cleared": cleared})

    # ── 项目管理端点（启停 daemon / 软删除） ──────────────

    def _resolve_project_or_400(self, path: str, prefix: str, require_exists: bool = True):
        """从 /api/projects/<name>[/start|/stop|/restart] 或 /api/projects/<name> 解析项目名。

        路径可能带 /start、/stop、/restart 动作后缀，先剥离再按项目名匹配。
        项目不存在（不在监控列表）返回 None；require_exists 时目录不存在也返回 None，
        调用方发 400。删除接口传 require_exists=False 以支持移除缺失项目。
        """
        if not path.startswith(prefix):
            return None
        name = urllib.parse.unquote(path[len(prefix):])
        # 剥离可能的动作后缀（/start、/stop、/restart）
        for suffix in ("/start", "/stop", "/restart"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        if not name:
            return None
        project = self.server.project_by_name(name)
        if project is None or (require_exists and not project.get("exists")):
            return None
        return project

    def _api_project_lifecycle(self, action: str, path: str, query: dict):
        """POST /api/projects/<name>/start|stop|restart。成功广播 refresh 让概览自动刷新。

        restart 走 supervisor 优雅重启协议（写 .fenix/restart_request，与
        hook restart-daemon 同构）：daemon 自行排水退出后由 supervisor 拉起，
        dashboard 进程不直接杀/拉 daemon。
        """
        project = self._resolve_project_or_400(path, "/api/projects/")
        if project is None:
            self._error(400, "项目不存在或未监控")
            return
        try:
            if action == "start":
                result = start_daemon(project["path"])
            elif action == "stop":
                result = stop_daemon(project["path"])
            else:  # restart
                req_path = Path(project["path"]) / ".fenix" / "restart_request"
                try:
                    req_path.parent.mkdir(parents=True, exist_ok=True)
                    req_path.touch()
                    result = {"ok": True, "error": None,
                              "requested": True, "session": None}
                except OSError as e:
                    result = {"ok": False, "error": f"写入 restart_request 失败: {e}"}
        except Exception as e:  # 环境异常（tmux 不可用等）→ 返回错误对象，不 500
            self._json({"ok": False, "error": f"操作失败: {e}"})
            return
        if not result.get("ok"):
            self._json({"ok": False, "error": result.get("error", "未知错误")})
            return
        # 成功：广播 refresh，概览在自动刷新周期内跟随更新 daemon 状态
        try:
            self.server.sse_hub.broadcast({"type": "refresh"})
        except Exception:
            pass
        self._json({
            "ok": True,
            "session": result.get("session"),
            "already": result.get("already", False),
            "was_running": result.get("was_running", False),
        })

    def _api_project_delete(self, path: str, query: dict):
        """DELETE /api/projects/<name> —— 软删除：停止 daemon + 写入忽略列表。

        缺失项目（目录已不存在，exists=false）也允许删除：跳过停止 daemon，
        仅从监控列表移除并写入忽略列表。
        """
        project = self._resolve_project_or_400(path, "/api/projects/", require_exists=False)
        if project is None:
            self._error(400, "项目不存在或未监控")
            return
        errors = []
        # 1) 停止 daemon（幂等，未运行不报错；缺失项目目录已不存在，跳过）
        if project.get("exists"):
            try:
                stop_result = stop_daemon(project["path"])
                if not stop_result.get("ok"):
                    errors.append(stop_result.get("error", "停止 daemon 失败"))
            except Exception as e:
                errors.append(f"停止 daemon 失败: {e}")
        # 2) 停止显式注册项 + 写入忽略列表（忽略优先：即便再次显式注册也被忽略）
        try:
            self.server.registry.remove_project(project["path"])
        except Exception:
            pass
        try:
            add_result = self.server.registry.add_ignored(project["path"])
            if not add_result[0]:
                errors.append(add_result[1])
        except Exception as e:
            errors.append(f"写入忽略列表失败: {e}")
        if errors:
            self._json({"ok": False, "error": "；".join(errors)})
            return
        # 成功：广播 refresh，概览不再返回该项目
        try:
            self.server.sse_hub.broadcast({"type": "refresh"})
        except Exception:
            pass
        self._json({"ok": True, "path": project["path"]})

    # ── POST API ────────────────────────────────────────────

    def _handle_api_post(self, path: str, query: dict):
        if path == "/api/config":
            self._api_config_post(query)
        elif path == "/api/config/sync-from-user":
            self._api_config_sync_from_user(query)
        elif path == "/api/prompts":
            self._api_prompts_post(query)
        elif path == "/api/todo":
            self._api_todo_post(query)
        elif path == "/api/verify-yaml":
            self._api_verify_yaml_post(query)
        elif path == "/api/verify-yaml-autodraft":
            self._api_verify_yaml_autodraft_post(query)
        elif path == "/api/spec-error-clear":
            self._api_spec_error_clear(query)
        elif path == "/api/spec-priority":
            self._api_spec_priority(query)
        elif path == "/api/spec-delete":
            self._api_spec_delete(query)
        elif path == "/api/spec-admin-invoke":
            self._api_spec_admin_invoke(query)
        elif path == "/api/run-cancel":
            self._api_run_cancel(query)
        elif path == "/api/spec-freeze":
            self._api_spec_freeze(query)
        elif path == "/api/spec-unfreeze":
            self._api_spec_unfreeze(query)
        elif path == "/api/spec-start-after":
            self._api_spec_start_after(query)
        elif path == "/api/spec-freeze-config":
            self._api_spec_freeze_config(query)
        elif path == "/api/spec-budget":
            self._api_spec_budget(query)
        elif path == "/api/spec-archive":
            self._api_spec_archive(query)
        elif path == "/api/spec-promote":
            self._api_spec_promote(query)
        elif path == "/api/spec-approve-push":
            self._api_spec_approve_push(query)
        elif path == "/api/alerts/clear":
            self._api_alerts_clear()
        elif path.startswith("/api/alerts/") and path.endswith("/handled"):
            alert_id = urllib.parse.unquote(path[len("/api/alerts/"):-len("/handled")])
            self._api_alert_handled(alert_id, query)
        elif path.startswith("/api/runs/") and path.endswith("/watch"):
            rest = urllib.parse.unquote(path[len("/api/runs/"):-len("/watch")])
            self._json(self._api_run_watch(rest, query, watch=True))
        elif path == "/api/project/describe":
            self._api_project_describe(query)
        elif path.endswith("/start"):
            # POST /api/projects/<name>/start —— 启动项目 daemon
            self._api_project_lifecycle("start", path, query)
        elif path.endswith("/stop"):
            # POST /api/projects/<name>/stop —— 停止项目 daemon
            self._api_project_lifecycle("stop", path, query)
        elif path.endswith("/restart"):
            # POST /api/projects/<name>/restart —— 优雅重启项目 daemon
            self._api_project_lifecycle("restart", path, query)
        else:
            self._error(404, "Not Found")

    def _handle_api_delete(self, path: str, query: dict):
        if path.startswith("/api/runs/") and path.endswith("/watch"):
            rest = urllib.parse.unquote(path[len("/api/runs/"):-len("/watch")])
            self._json(self._api_run_watch(rest, query, watch=False))
        elif path.startswith("/api/projects/") and len(path) > len("/api/projects/"):
            # DELETE /api/projects/<name> —— 软删除项目（停止 + 忽略列表）
            self._api_project_delete(path, query)
        else:
            self._error(404, "Not Found")

    def _read_json_body(self) -> dict:
        """读取并解析 JSON 请求体，做大小限制。失败返回 None 并自行发送错误。"""
        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._error(400, "Invalid Content-Length")
            return None
        if content_length <= 0:
            self._error(400, "Empty request body")
            return None
        if content_length > MAX_POST_BODY:
            self._error(413, "Request body too large")
            return None
        try:
            raw = self.rfile.read(content_length)
            body = json.loads(raw.decode("utf-8"))
            if not isinstance(body, dict):
                self._error(400, "Request body must be a JSON object")
                return None
            return body
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._error(400, "Invalid JSON body")
            return None

    def _api_config_post(self, query):
        body = self._read_json_body()
        if body is None:
            return

        project = self._project_from_query(query)
        if project is None:
            # 用户模式：写 ~/.fenix/config.yaml
            result = dashboard_data.write_config(None, body, scope="user")
        else:
            if not project.get("exists"):
                self._error(400, "project not found")
                return
            result = dashboard_data.write_config(project["path"], body, scope="project")

        if not result["ok"]:
            self._error(400, result["error"] or "配置写入失败")
            return

        # 成功后返回最新配置（读回以确认）+ scope / 写入路径
        if project is None:
            config = dashboard_data.read_config(None, scope="user")
        else:
            config = dashboard_data.read_effective_config(project["path"])
            config["project"] = project["name"]
        config["saved"] = True
        config["scope"] = result["scope"]
        config["path"] = result["path"]
        self._json(config)

    def _api_config_sync_from_user(self, query):
        """POST /api/config/sync-from-user?project=<name>  body: {"page": "<页标识>"}

        把用户级 config.yaml 中 page 页签对应的受管键覆盖写入项目级配置
        （设置页项目级「同步用户级设置」按钮）。page 白名单见
        data._SYNC_PAGE_KEYS；成功返回最新项目级生效配置（读回以确认）。
        """
        body = self._read_json_body()
        if body is None:
            return
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(400, "project not found")
            return
        page = body.get("page")
        if not isinstance(page, str) or not page:
            self._error(400, "body.page 必须为页面标识字符串")
            return
        result = dashboard_data.sync_config_from_user(project["path"], page)
        if not result["ok"]:
            self._error(400, result.get("error") or "同步失败")
            return
        config = dashboard_data.read_effective_config(project["path"])
        config["project"] = project["name"]
        config["saved"] = True
        config["synced"] = result["synced"]
        self._json(config)

    def _api_project_describe(self, query):
        """POST /api/project/describe?project=<name>

        由后端调用 headless claude CLI 生成项目简介。
        - 读项目根 README.md（≤8KB 截断，缺失时改读 package.json/pyproject.toml 前 4KB）
        - 拼固定中文指令 prompt
        - subprocess.run(["claude", "-p", prompt], cwd=项目根, timeout=120, shell=False)
        - 成功经 write_config 落盘返回 {ok, description}
        - 非零退出/超时/空输出返回 {error} 且不改 config
        """
        project = self._project_from_query(query)
        if project is None:
            self._error(400, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return

        proot = Path(project["path"])
        # 读取项目文件内容
        content = ""
        readme_path = proot / "README.md"
        if readme_path.exists():
            try:
                raw = readme_path.read_bytes()[:8192]  # ≤8KB 截断
                content = raw.decode("utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                content = ""
        else:
            # 缺失时改读 package.json/pyproject.toml 前 4KB
            for fallback in ["package.json", "pyproject.toml"]:
                fallback_path = proot / fallback
                if fallback_path.exists():
                    try:
                        raw = fallback_path.read_bytes()[:4096]  # 前 4KB
                        content = raw.decode("utf-8", errors="replace")
                        break
                    except (OSError, UnicodeDecodeError):
                        continue

        # 拼固定中文指令 prompt（必须携带项目名与路径——README 主题重叠的
        # 项目若无项目身份信息会生成彼此的简介）
        prompt = f"""你是一个项目简介生成器。请为项目「{project["name"]}」（位于 {proot}）生成一句约100字的中文项目简介。

以下是该项目说明文件的内容：
{content}

要求：
1. 生成的简介必须围绕项目「{project["name"]}」本身，是纯文本，不要包含任何标记语言
2. 说明文件内容可能与同生态其他项目相似甚至过时：若它无法体现本项目的独特功能，
   请查看项目目录中的实际文件（如 package.json 的 name/description、pyproject.toml、
   主要源码结构）来确认项目定位，简介以项目实际功能为准
3. 简介应该概括该项目的主要用途和特点，注意区分于同生态下的其他项目
4. 简介长度控制在100字左右
5. 只输出简介文本，不要有其他内容"""

        # 调用 headless claude CLI
        import subprocess
        try:
            result = subprocess.run(
                ["claude", "-p", prompt],
                cwd=str(proot),
                timeout=120,
                shell=False,
                capture_output=True,
                text=True
            )
        except subprocess.TimeoutExpired:
            self._json({"error": "生成超时"})
            return
        except Exception as e:
            self._json({"error": f"调用 claude CLI 失败: {str(e)}"})
            return

        # 检查返回结果
        if result.returncode != 0:
            self._json({"error": f"claude CLI 返回非零退出码: {result.returncode}"})
            return

        description = result.stdout.strip()
        if not description:
            self._json({"error": "生成的简介为空"})
            return

        # 写入配置
        write_result = dashboard_data.write_config(
            proot, {"description": description}, scope="project"
        )
        if not write_result["ok"]:
            self._json({"error": f"配置写入失败: {write_result.get('error', '未知错误')}"})
            return

        self._json({"ok": True, "description": description})

    def _project_from_query(self, query):
        name = query.get("project", [None])[0]
        if not name:
            return None
        return self.server.project_by_name(name)

    # ── SSE 推送流 ──────────────────────────────────────────────

    def _handle_sse(self):
        """GET /api/stream —— 常驻 SSE 长连接，收到 watcher 广播即推送。

        首次事件为 hello（携带 cid，供前端注册 run 增量订阅）；此后持续阻塞
        读取连接事件队列，25s 无事件发心跳注释帧保活。客户端断开即清理。
        活跃连接数 ≥ MAX_SSE_CONNECTIONS 时拒绝（503 + JSON 错误体），
        客户端收到后应退化为轮询（dashboard-connection-limit D6）。
        为及时释放连接槽位（释放后恢复可测），除写心跳外每个队列超时
        （≤1s）做一次客户端 socket 可读探测：客户端 FIN → 立即 unregister。
        """
        conn = self.server.sse_hub.register()
        if conn is None:
            self._error(503, "too many SSE connections")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            self._sse_send({"type": "hello", "cid": conn.id})
            last_heartbeat = time.monotonic()
            while True:
                try:
                    event = conn.queue.get(timeout=SSE_CLIENT_POLL_INTERVAL)
                except queue.Empty:
                    # 客户端断开探测：可读且 recv 返回 b""（EOF/FIN）即已断开
                    if self._sse_client_gone():
                        break
                    # 25s 心跳保活
                    if time.monotonic() - last_heartbeat >= 25:
                        self._sse_send(None)
                        last_heartbeat = time.monotonic()
                    continue
                if event is None:  # 关闭信号
                    break
                self._sse_send(event)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.server.sse_hub.unregister(conn)

    def _sse_client_gone(self) -> bool:
        """探测 SSE 客户端 socket 是否已关闭（FIN）。

        用 select 探测可读性 + recv(MSG_PEEK) 判 EOF，不消费任何真实数据，
        避免误读浏览器可能发送的其它字节。
        """
        import select
        try:
            r, _, _ = select.select([self.connection], [], [], 0)
        except (OSError, ValueError):
            return True
        if not r:
            return False
        try:
            data = self.connection.recv(1, socket.MSG_PEEK)
        except (BlockingIOError, OSError, ValueError):
            return True
        return data == b""

    def _sse_send(self, event: dict | None):
        """以 HTTP/1.1 chunked 帧写入一条 SSE 消息；event=None 写心跳注释。

        不带 event: 命名行——命名事件不触发前端 onmessage，只有默认事件才触发；
        事件类型已由 data 中的 type 字段区分。
        """
        if event is None:
            frame = b": ping\n\n"
        else:
            data = json.dumps(event, ensure_ascii=False)
            frame = ("data: %s\n\n" % data).encode("utf-8")
        chunk = b"%X\r\n" % len(frame) + frame + b"\r\n"
        self.wfile.write(chunk)
        self.wfile.flush()

    # ── 静态资源与截图 ────────────────────────────────────────

    def _serve_static(self, filename: str):
        static_root = self.server.static_dir.resolve()
        target = (static_root / filename).resolve()
        # 防路径穿越：解析后必须仍在 static 目录内
        if not target.is_relative_to(static_root):
            self._error(404, "Not Found")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            # v3 SPA 直接挂载在 / 时，index.html 内相对资源（./umi.js）
            # 会以根路径请求；回退映射到 dist/ 目录
            target = static_root / "dist" / filename
            if not target.is_relative_to(static_root) or not target.is_file():
                self._error(404, "Not Found")
                return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        # 构建产物文件名带内容 hash，可安全长缓存；index.html 不缓存
        cache = "no-cache"
        if target.name != "index.html" and self._HASHED_STATIC_RE.search(target.name):
            cache = "max-age=31536000, immutable"
        self._send_file(target, ctype, cache=cache)

    def _serve_screenshot(self, path: str):
        # /screenshots/<project>/<spec>/<file>
        parts = path.split("/")
        # ['', 'screenshots', project, spec, file...]
        if len(parts) < 5:
            self._error(404, "Not Found")
            return
        project_name = urllib.parse.unquote(parts[2])
        spec = urllib.parse.unquote(parts[3])
        file_part = "/".join(parts[4:])

        project = self.server.project_by_name(project_name)
        if project is None or not project.get("exists"):
            self._error(403, "Forbidden")
            return

        screenshots_dir = (
            Path(project["path"]) / ".fenix" / "verify-progress" / spec / "screenshots"
        ).resolve()
        target = (screenshots_dir / file_part).resolve()

        # 防路径穿越：解析后必须仍位于该项目 screenshots 目录内
        if not target.is_relative_to(screenshots_dir):
            self._error(403, "Forbidden")
            return
        if not target.is_file() or target.suffix.lower() not in ALLOWED_IMAGE_EXT:
            self._error(404, "Not Found")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "image/png"
        self._send_file(target, ctype)

    _HASHED_STATIC_RE = re.compile(r"\.[0-9a-f]{8,}(?:\.async)?\.(?:js|css)$")
    # 文本类才值得 gzip（图片/字体本身已二进制压缩）；svg mimetypes 给
    # image/*，故按后缀白名单而非 ctype 判断
    _GZIP_EXT = {".js", ".css", ".html", ".htm", ".svg", ".json", ".md", ".txt", ".map"}
    _GZIP_MIN = 860  # 小于阈值的响应不值得压缩

    def _wants_gzip(self) -> bool:
        return "gzip" in self.headers.get("Accept-Encoding", "").lower()

    def _maybe_gzip(self, body: bytes) -> bytes:
        if len(body) >= self._GZIP_MIN and self._wants_gzip():
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
            return gzip.compress(body, 5)
        return body

    def _send_file(self, path: Path, ctype: str, cache: str = "no-cache"):
        try:
            body = path.read_bytes()
        except OSError:
            self._error(404, "Not Found")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", cache)
        if path.suffix.lower() in self._GZIP_EXT:
            body = self._maybe_gzip(body)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        body = self._maybe_gzip(body)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, code: int, msg: str):
        # 与 _json 保持一致用 ensure_ascii=False，中文错误文案以可读字面输出
        body = json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


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
        fields = data[data.rindex(")") + 2:].split()
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
            f"{pid}）——agent run 已结束，本实例自杀以避免孤儿泄漏。\n")
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(
        target=_claude_watchdog_loop, args=(pid, starttime),
        kwargs={"on_death": _terminate}, daemon=True, name="claude-watchdog",
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
            "父进程退出后本实例不会自动终止，请注意。\n")
    if os.getppid() == 1:
        sys.stderr.write(
            "dashboard serve 检测到父进程已退出（PPID=1，孤儿启动）——拒绝启动。\n"
            "长驻/后台运行请使用 fenix_dashboard.py --serve 入口，"
            "或显式设置 FENIX_DASHBOARD_DETACH=1。\n")
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
            ("127.0.0.1", actual), registry,
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
                    ("127.0.0.1", actual), registry,
                    static_dir or STATIC_DIR,
                )
            except OSError as e2:
                sys.stderr.write(
                    f"端口 {actual} 接管旧 dashboard 实例后仍无法绑定：{e2}\n")
                sys.exit(1)
        else:
            # 占用者为非 dashboard 进程（或无法判定）→ 明确报错非 0 退出
            info = occupant["cmdline"] if occupant else "未知进程"
            pid = occupant["pid"] if occupant else "?"
            sys.stderr.write(
                f"端口 {actual} 已被占用（PID {pid}，cmdline: {info}）；\n"
                f"该占用者不是 fenix_dashboard.py --serve 实例，恕不接管。\n"
                f"请释放该端口后重试，或使用其它 --port。\n")
            sys.exit(1)

    watcher = FileWatcher(lambda: httpd.projects(), httpd.sse_hub,
                         summary_index=httpd.summary_index)
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

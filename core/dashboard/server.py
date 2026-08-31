"""
server.py — Fenix Web Dashboard 服务器（dashboard-server）。

- 基于 Python 标准库 http.server.ThreadingHTTPServer，零新增依赖（D2）。
- 仅绑定 127.0.0.1，默认端口 8787；被占用时由 serve() 执行端口接管语义
  （dashboard-instance-lifecycle）：旧 dashboard --serve 实例自动终止接管，
  非 dashboard 进程占用则报错退出，绝不静默僵挂。
- REST JSON API + 截图等静态资源服务。
- 所有 API 容错：数据源损坏以字段标记返回，不 500。

端点：
    GET /                          → index.html
    GET /app.js /style.css         → 前端静态资源
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
    POST /api/spec-admin-invoke?project=<name>&spec=<name>  → 手动唤起 Admin（写 .fenix/admin_invoke_request.json，进行中返回 409）
    GET /api/config?project=<name> → 读取受管配置（llm / agents.models / gates.approve_mode）
    POST /api/config?project=<name> → 写回受管配置（原子写、校验失败返回 400）
    GET /api/alerts?project=<name> → Administrator 告警/处置记录（缺省跨项目聚合未处理告警）
    POST /api/alerts/<id>/handled?project=<name> → 标记升级告警已处理
    POST /api/alerts/clear → 清理所有事件：全部项目未处理告警一次标记已处理
    GET /api/admin-activities?project=<name> → Administrator 活动记录（运维记录时间线，未处理升级关联置顶）
    GET /screenshots/<project>/<spec>/<file> → 截图（防路径穿越，仅限注册项目）
"""

import json
import mimetypes
import os
import queue
import sys
import signal
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import data as dashboard_data
from .registry import Registry
from .watcher import FileWatcher
from core.fenix_session import start_daemon, stop_daemon

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


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

    def register(self) -> SSEConnection:
        with self._lock:
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
        self.watcher = None  # serve() 中创建并启动
        self._projects_cache = []
        self._cache_ts = 0.0
        self._cache_ttl = 10.0

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
                self._serve_static("index.html")
            elif path.startswith("/screenshots/"):
                self._serve_screenshot(path)
            else:
                # 其它静态资源（/app.js /style.css /vendor/*）；_serve_static 内含防穿越校验
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
        elif path == "/api/spec-doc":
            self._json(self._api_spec_doc(query))
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
        specs = dashboard_data.parse_state(proot)
        items = [
            dashboard_data.spec_summary(proot, name, entry)
            for name, entry in specs.items()
        ]
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

    def _api_spec_delete(self, query):
        """POST /api/spec-delete?project=<name>&spec=<name>

        软删除 SPEC：STATE.md 移除条目 + openspec 目录移入 archive。
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
        proot = Path(project["path"])
        try:
            result = dashboard_data.request_admin_invoke(proot, spec)
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
        """从 /api/projects/<name>[/start|/stop] 或 /api/projects/<name> 解析项目名。

        路径可能带 /start、/stop 动作后缀，先剥离再按项目名匹配。
        项目不存在（不在监控列表）返回 None；require_exists 时目录不存在也返回 None，
        调用方发 400。删除接口传 require_exists=False 以支持移除缺失项目。
        """
        if not path.startswith(prefix):
            return None
        name = urllib.parse.unquote(path[len(prefix):])
        # 剥离可能的动作后缀（/start、/stop）
        for suffix in ("/start", "/stop"):
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
        """POST /api/projects/<name>/start|stop。成功广播 refresh 让概览自动刷新。"""
        project = self._resolve_project_or_400(path, "/api/projects/")
        if project is None:
            self._error(400, "项目不存在或未监控")
            return
        try:
            if action == "start":
                result = start_daemon(project["path"])
            else:
                result = stop_daemon(project["path"])
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
        elif path == "/api/spec-error-clear":
            self._api_spec_error_clear(query)
        elif path == "/api/spec-priority":
            self._api_spec_priority(query)
        elif path == "/api/spec-delete":
            self._api_spec_delete(query)
        elif path == "/api/spec-admin-invoke":
            self._api_spec_admin_invoke(query)
        elif path == "/api/alerts/clear":
            self._api_alerts_clear()
        elif path.startswith("/api/alerts/") and path.endswith("/handled"):
            alert_id = urllib.parse.unquote(path[len("/api/alerts/"):-len("/handled")])
            self._api_alert_handled(alert_id, query)
        elif path.startswith("/api/runs/") and path.endswith("/watch"):
            rest = urllib.parse.unquote(path[len("/api/runs/"):-len("/watch")])
            self._json(self._api_run_watch(rest, query, watch=True))
        elif path.endswith("/start"):
            # POST /api/projects/<name>/start —— 启动项目 daemon
            self._api_project_lifecycle("start", path, query)
        elif path.endswith("/stop"):
            # POST /api/projects/<name>/stop —— 停止项目 daemon
            self._api_project_lifecycle("stop", path, query)
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
        """
        conn = self.server.sse_hub.register()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            self._sse_send({"type": "hello", "cid": conn.id})
            while True:
                try:
                    event = conn.queue.get(timeout=25)
                except queue.Empty:
                    self._sse_send(None)  # 心跳注释帧
                    continue
                if event is None:  # 关闭信号
                    break
                self._sse_send(event)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            self.server.sse_hub.unregister(conn)

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
        target = (self.server.static_dir / filename).resolve()
        static_root = self.server.static_dir.resolve()
        if not target.is_relative_to(static_root) or not target.is_file():
            self._error(404, "Not Found")
            return
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send_file(target, ctype)

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

    def _send_file(self, path: Path, ctype: str):
        try:
            body = path.read_bytes()
        except OSError:
            self._error(404, "Not Found")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, code: int, msg: str):
        body = json.dumps({"error": msg}).encode("utf-8")
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


def serve(registry: Registry, port: int = 8787, static_dir=None):
    """启动 Dashboard 服务（阻塞）。

    端口独占语义（dashboard-instance-lifecycle）：目标端口被占用时，
    - 占用者为旧的 `fenix_dashboard.py --serve` 实例 → SIGTERM 终止旧实例，
      等待其退出（≤3s）后重新绑定一次；
    - 占用者为其它进程（非 dashboard 实例）→ 打印占用信息后非 0 退出；
    - 任何启动失败 MUST 在 5 秒内退出，不留僵尸实例。
    仅对最终确定的单一端口做上述占用检测（不再自动上探）。
    """
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

    watcher = FileWatcher(lambda: httpd.projects(), httpd.sse_hub)
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

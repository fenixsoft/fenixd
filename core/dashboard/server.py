"""
server.py — Fenix Web Dashboard 服务器（dashboard-server）。

- 基于 Python 标准库 http.server.ThreadingHTTPServer，零新增依赖（D2）。
- 仅绑定 127.0.0.1，默认端口 8787；被占用时自动向上探测空闲端口（D7）。
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
    GET /api/config?project=<name> → 读取受管配置（llm / agents.models / gates.approve_mode）
    POST /api/config?project=<name> → 写回受管配置（原子写、校验失败返回 400）
    GET /api/alerts?project=<name> → Administrator 告警/处置记录（缺省跨项目聚合未处理告警）
    POST /api/alerts/<id>/handled?project=<name> → 标记升级告警已处理
    GET /screenshots/<project>/<spec>/<file> → 截图（防路径穿越，仅限注册项目）
"""

import json
import mimetypes
import queue
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import data as dashboard_data
from .registry import Registry
from .watcher import FileWatcher

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
        elif path == "/api/config":
            self._json(self._api_config_get(query))
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
            return {"error": "unknown project"}
        if not project.get("exists"):
            return {"error": "project not found"}
        config = dashboard_data.read_config(project["path"])
        config["project"] = project["name"]
        return config

    def _api_alerts(self, query) -> dict:
        """读取 Administrator 告警。

        ?project=<name> → 该项目全部告警/处置记录 + 摘要；
        缺省 → 跨项目聚合所有未处理升级告警（供顶部横幅）。
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
        all_unhandled.sort(key=lambda a: a.get("created", ""), reverse=True)
        return {
            "total_unhandled": total,
            "projects": projects_out,
            "alerts": all_unhandled,
        }

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

    # ── POST API ────────────────────────────────────────────

    def _handle_api_post(self, path: str, query: dict):
        if path == "/api/config":
            self._api_config_post(query)
        elif path.startswith("/api/alerts/") and path.endswith("/handled"):
            alert_id = urllib.parse.unquote(path[len("/api/alerts/"):-len("/handled")])
            self._api_alert_handled(alert_id, query)
        elif path.startswith("/api/runs/") and path.endswith("/watch"):
            rest = urllib.parse.unquote(path[len("/api/runs/"):-len("/watch")])
            self._json(self._api_run_watch(rest, query, watch=True))
        else:
            self._error(404, "Not Found")

    def _handle_api_delete(self, path: str, query: dict):
        if path.startswith("/api/runs/") and path.endswith("/watch"):
            rest = urllib.parse.unquote(path[len("/api/runs/"):-len("/watch")])
            self._json(self._api_run_watch(rest, query, watch=False))
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
        project = self._project_from_query(query)
        if project is None:
            self._error(400, "unknown project")
            return
        if not project.get("exists"):
            self._error(400, "project not found")
            return

        body = self._read_json_body()
        if body is None:
            return

        result = dashboard_data.write_config(project["path"], body)
        if not result["ok"]:
            self._error(400, result["error"] or "配置写入失败")
            return

        # 成功后返回最新配置（读回以确认）
        config = dashboard_data.read_config(project["path"])
        config["project"] = project["name"]
        config["saved"] = True
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


def serve(registry: Registry, port: int = 8787, static_dir=None):
    """启动 Dashboard 服务（阻塞）。端口被占用时自动向上探测。"""
    actual = find_free_port(port)
    httpd = DashboardHTTPServer(
        ("127.0.0.1", actual), registry,
        static_dir or STATIC_DIR,
    )
    watcher = FileWatcher(lambda: httpd.projects(), httpd.sse_hub)
    httpd.watcher = watcher
    watcher.start()
    url = f"http://localhost:{actual}"
    # flush=True：被 Ctrl+C / timeout 杀进程时 URL 必须已输出（供 skill 解析）
    print("=" * 60, flush=True)
    print("  Fenix Web Dashboard", flush=True)
    print(f"  地址: {url}", flush=True)
    print(f"  端口: {actual}（默认 {port} 被占用则自动上探）", flush=True)
    print("  Ctrl+C 退出", flush=True)
    print("=" * 60, flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard 已退出")
    finally:
        watcher.stop()
        httpd.server_close()

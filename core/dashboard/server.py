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
    GET /screenshots/<project>/<spec>/<file> → 截图（防路径穿越，仅限注册项目）
"""

import json
import mimetypes
import socket
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import data as dashboard_data
from .registry import Registry

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


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


class DashboardHandler(BaseHTTPRequestHandler):
    """只处理 GET/HEAD 请求，输出 JSON 或静态资源。"""

    server: DashboardHTTPServer  # 类型标注，便于 IDE

    # ── 基础 ─────────────────────────────────────────────────

    def do_GET(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def log_message(self, fmt, *args):
        # 静默访问日志，避免污染运行终端
        pass

    def _handle(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query)

            if path == "/" or path == "/index.html":
                self._serve_static("index.html")
            elif path in ("/app.js", "/style.css"):
                self._serve_static(path.lstrip("/"))
            elif path == "/api/projects":
                self._json(self._api_projects())
            elif path == "/api/overview":
                self._json(self._api_overview())
            elif path == "/api/specs":
                self._json(self._api_specs(query))
            elif path.startswith("/api/specs/"):
                spec = urllib.parse.unquote(path[len("/api/specs/"):])
                self._json(self._api_spec_detail(spec, query))
            elif path.startswith("/api/runs/"):
                run_id = urllib.parse.unquote(path[len("/api/runs/"):])
                self._json(self._api_run(run_id, query))
            elif path == "/api/events":
                self._json(self._api_events(query))
            elif path.startswith("/screenshots/"):
                self._serve_screenshot(path)
            else:
                self._error(404, "Not Found")
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001 兜底：绝不让请求崩溃进程
            try:
                self._error(500, f"Internal Server Error: {e}")
            except Exception:
                pass

    # ── API 实现 ─────────────────────────────────────────────

    def _api_projects(self) -> dict:
        projects = []
        for p in self.server.projects():
            if not p.get("exists"):
                projects.append({
                    "name": p["name"], "path": p["path"],
                    "discovered": p.get("discovered", False),
                    "exists": False, "error": "项目路径不存在",
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
        items.sort(key=lambda s: (s.get("status") != "pushed", s.get("priority", 999)))
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
        run = dashboard_data.get_run_events(Path(project["path"]), run_id)
        run["project"] = project["name"]
        return run

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

    def _project_from_query(self, query):
        name = query.get("project", [None])[0]
        if not name:
            return None
        return self.server.project_by_name(name)

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
        httpd.server_close()

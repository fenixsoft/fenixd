"""base.py — H0 HTTP 底座（refactor-giant-classes D1/D3/D5）。

原为 DashboardHandler 的 HTTP 底座方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin
（MRO 中资源组排在 BaseHTTPRequestHandler 之前）。

D3 patch 缝隙：
- `MAX_POST_BODY` 常量仍定义在 `core.dashboard.server` 命名空间（测试
  monkeypatch 该命名空间属性）——本模块经 `core.dashboard.server`
  命名空间延迟解析；
- `_GZIP_EXT`/`_GZIP_MIN` 类常量随本 mixin 迁移（无外部 patch 依赖）。

H1 路由分派链（`_handle_api`/`_handle_api_post`/`_handle_api_delete`）
随各资源子路由摘出后收敛为表驱动（design D1 表 C H1，task 4.5）；
本模块仅承载 H0 HTTP 底座（不含分派链）。
"""

from __future__ import annotations

import gzip
import json
import urllib.parse


# ── H1 路由分派链（design D1 表 C H1，task 4.5）──────────────────────
# 表驱动 + 按资源委派。路由表条目含可扫描 pattern 字面量（design D4
# task 4.6 gen-route-map 扫描源），按注册顺序匹配。精确路由优先于
# 前缀/后缀（表序即优先级），MUST NOT 让裸后缀 matcher 前置精确 matcher。
# POST 链 4 个裸 endswith（/start /stop /restart /install-hosting）
# 是方法**最后 4 个分支**，须排在 /api/project/describe 之后（保留陷阱）。
# DELETE 的 /api/projects/<name> 在独立方法中。
#
# 条目结构: (kind, pattern, handler, json_flag)
#   kind   ∈ {"exact", "regex", "suffix"}
#   pattern: 路由字面量（精确匹配串 / 正则 pattern / 后缀串）
#   handler: handler 函数引用（self, path, query, m） → None
#   json_flag: handler 返回 dict 时自动包 _json（True）或 handler 已写响应（False）
#
# 参数化路径用 regex capture group（/api/specs/<spec>、/api/runs/<id>、
# /api/alerts/<id>/handled、/api/projects/<name>）。

def _r_json(s, p, q, m, payload):
    """json 包装适配器：handler 返回 payload 时包 _json。"""
    s._json(payload)


# ── GET 路由适配函数 ──────────────────────────────────────────────────

def _get_projects(s, p, q, m):
    s._json(s._api_projects())

def _get_overview(s, p, q, m):
    s._json(s._api_overview())

def _get_specs(s, p, q, m):
    s._json(s._api_specs(q))

def _get_spec_detail(s, p, q, m):
    spec = urllib.parse.unquote(m.group(1))
    s._json(s._api_spec_detail(spec, q))

def _get_runs_watch(s, p, q, m):
    rest = urllib.parse.unquote(m.group(1))
    if rest.endswith("/watch"):
        s._json(s._api_run_watch(rest[: -len("/watch")], q, watch=True))
    else:
        s._json(s._api_run(rest, q))

def _get_events(s, p, q, m):
    s._json(s._api_events(q))

def _get_alerts(s, p, q, m):
    s._json(s._api_alerts(q))

def _get_admin_activities(s, p, q, m):
    s._json(s._api_admin_activities(q))

def _get_config(s, p, q, m):
    s._json(s._api_config_get(q))

def _get_hooks_audit(s, p, q, m):
    s._json(s._api_hooks_audit(q))

def _get_prompts(s, p, q, m):
    s._json(s._api_prompts_get(q))

def _get_todo(s, p, q, m):
    s._api_todo_get(q)

def _get_verify_yaml(s, p, q, m):
    s._api_verify_yaml_get(q)

def _get_verify_yaml_template(s, p, q, m):
    s._api_verify_yaml_template()

def _get_spec_doc(s, p, q, m):
    s._json(s._api_spec_doc(q))

def _get_help_docs(s, p, q, m):
    s._json(s._api_help_docs())

def _get_help_doc(s, p, q, m):
    s._api_help_doc(q)

def _get_evolution_items(s, p, q, m):
    s._api_evolution_items(q)

def _get_evolution_analysis(s, p, q, m):
    s._api_evolution_analysis(q)

def _get_evolution_draft(s, p, q, m):
    s._api_evolution_draft(q)


# ── POST 路由适配函数 ─────────────────────────────────────────────────

def _post_config(s, p, q, m):
    s._api_config_post(q)

def _post_config_sync(s, p, q, m):
    s._api_config_sync_from_user(q)

def _post_prompts(s, p, q, m):
    s._api_prompts_post(q)

def _post_todo(s, p, q, m):
    s._api_todo_post(q)

def _post_verify_yaml(s, p, q, m):
    s._api_verify_yaml_post(q)

def _post_verify_yaml_autodraft(s, p, q, m):
    s._api_verify_yaml_autodraft_post(q)

def _post_spec_error_clear(s, p, q, m):
    s._api_spec_error_clear(q)

def _post_spec_priority(s, p, q, m):
    s._api_spec_priority(q)

def _post_spec_delete(s, p, q, m):
    s._api_spec_delete(q)

def _post_spec_admin_invoke(s, p, q, m):
    s._api_spec_admin_invoke(q)

def _post_run_cancel(s, p, q, m):
    s._api_run_cancel(q)

def _post_spec_freeze(s, p, q, m):
    s._api_spec_freeze(q)

def _post_spec_unfreeze(s, p, q, m):
    s._api_spec_unfreeze(q)

def _post_spec_start_after(s, p, q, m):
    s._api_spec_start_after(q)

def _post_spec_freeze_config(s, p, q, m):
    s._api_spec_freeze_config(q)

def _post_spec_budget(s, p, q, m):
    s._api_spec_budget(q)

def _post_spec_archive(s, p, q, m):
    s._api_spec_archive(q)

def _post_spec_promote(s, p, q, m):
    s._api_spec_promote(q)

def _post_spec_task_reflow(s, p, q, m):
    s._api_spec_task_reflow(q)

def _post_spec_re_review(s, p, q, m):
    s._api_spec_re_review(q)

def _post_spec_approve_push(s, p, q, m):
    s._api_spec_approve_push(q)

def _post_alerts_clear(s, p, q, m):
    s._api_alerts_clear()

def _post_evolution_accept(s, p, q, m):
    s._api_evolution_accept()

def _post_evolution_reject(s, p, q, m):
    s._api_evolution_reject()

def _post_evolution_delete(s, p, q, m):
    s._api_evolution_delete()

def _post_evolution_clear_todo(s, p, q, m):
    s._api_evolution_clear_todo()

def _post_alert_handled(s, p, q, m):
    alert_id = urllib.parse.unquote(m.group(1))
    s._api_alert_handled(alert_id, q)

def _post_run_watch(s, p, q, m):
    rest = urllib.parse.unquote(m.group(1))[: -len("/watch")]
    s._json(s._api_run_watch(rest, q, watch=True))

def _post_project_describe(s, p, q, m):
    s._api_project_describe(q)

# 4 个裸 endswith —— 排在 /api/project/describe 之后（保留顺序陷阱）

def _post_start(s, p, q, m):
    s._api_project_lifecycle("start", p, q)

def _post_stop(s, p, q, m):
    s._api_project_lifecycle("stop", p, q)

def _post_restart(s, p, q, m):
    s._api_project_lifecycle("restart", p, q)

def _post_install_hosting(s, p, q, m):
    s._api_project_lifecycle("install-hosting", p, q)


# ── DELETE 路由适配函数 ───────────────────────────────────────────────

def _del_run_watch(s, p, q, m):
    rest = urllib.parse.unquote(m.group(1))[: -len("/watch")]
    s._json(s._api_run_watch(rest, q, watch=False))

def _del_project(s, p, q, m):
    s._api_project_delete(p, q)


import re as _re

_API_GET_ROUTES = [
    # 精确路由（原 _handle_api if/elif 顺序保持优先级）
    ("exact", "/api/projects",         _get_projects),
    ("exact", "/api/overview",         _get_overview),
    ("exact", "/api/specs",            _get_specs),
    # 参数化前缀（regex）
    ("regex", r"^/api/specs/([^/]+)$", _get_spec_detail),
    ("regex", r"^/api/runs/(.+)$",     _get_runs_watch),
    ("exact", "/api/events",           _get_events),
    ("exact", "/api/alerts",           _get_alerts),
    ("exact", "/api/admin-activities", _get_admin_activities),
    ("exact", "/api/config",           _get_config),
    ("exact", "/api/hooks/audit",      _get_hooks_audit),
    ("exact", "/api/prompts",          _get_prompts),
    ("exact", "/api/todo",             _get_todo),
    ("exact", "/api/verify-yaml",      _get_verify_yaml),
    ("exact", "/api/verify-yaml-template", _get_verify_yaml_template),
    ("exact", "/api/spec-doc",         _get_spec_doc),
    ("exact", "/api/help/docs",        _get_help_docs),
    ("exact", "/api/help/doc",         _get_help_doc),
    ("exact", "/api/evolution/items",  _get_evolution_items),
    ("exact", "/api/evolution/analysis", _get_evolution_analysis),
    ("exact", "/api/evolution/draft",  _get_evolution_draft),
]

_API_POST_ROUTES = [
    # 精确路由（原顺序保持）
    ("exact", "/api/config",              _post_config),
    ("exact", "/api/config/sync-from-user", _post_config_sync),
    ("exact", "/api/prompts",             _post_prompts),
    ("exact", "/api/todo",                _post_todo),
    ("exact", "/api/verify-yaml",         _post_verify_yaml),
    ("exact", "/api/verify-yaml-autodraft", _post_verify_yaml_autodraft),
    ("exact", "/api/spec-error-clear",    _post_spec_error_clear),
    ("exact", "/api/spec-priority",       _post_spec_priority),
    ("exact", "/api/spec-delete",         _post_spec_delete),
    ("exact", "/api/spec-admin-invoke",   _post_spec_admin_invoke),
    ("exact", "/api/run-cancel",          _post_run_cancel),
    ("exact", "/api/spec-freeze",         _post_spec_freeze),
    ("exact", "/api/spec-unfreeze",       _post_spec_unfreeze),
    ("exact", "/api/spec-start-after",    _post_spec_start_after),
    ("exact", "/api/spec-freeze-config",  _post_spec_freeze_config),
    ("exact", "/api/spec-budget",         _post_spec_budget),
    ("exact", "/api/spec-archive",        _post_spec_archive),
    ("exact", "/api/spec-promote",        _post_spec_promote),
    ("exact", "/api/spec-task-reflow",    _post_spec_task_reflow),
    ("exact", "/api/spec-re-review",      _post_spec_re_review),
    ("exact", "/api/spec-approve-push",   _post_spec_approve_push),
    ("exact", "/api/alerts/clear",        _post_alerts_clear),
    ("exact", "/api/evolution/accept",    _post_evolution_accept),
    ("exact", "/api/evolution/reject",    _post_evolution_reject),
    ("exact", "/api/evolution/delete",    _post_evolution_delete),
    ("exact", "/api/evolution/clear-todo", _post_evolution_clear_todo),
    # 参数化 regex（/handled 和 /watch）
    ("regex", r"^/api/alerts/([^/]+)/handled$", _post_alert_handled),
    ("regex", r"^/api/runs/(.+)/watch$",        _post_run_watch),
    # /api/project/describe（精确，排在 endswith 之前）
    ("exact", "/api/project/describe",   _post_project_describe),
    # 裸 endswith（4 个，MUST 排最后——保留顺序陷阱）
    ("suffix", "/start",        _post_start),
    ("suffix", "/stop",         _post_stop),
    ("suffix", "/restart",      _post_restart),
    ("suffix", "/install-hosting", _post_install_hosting),
]

_API_DELETE_ROUTES = [
    ("regex",  r"^/api/runs/(.+)/watch$", _del_run_watch),
    ("regex",  r"^/api/projects/([^/]+)$", _del_project),
]


def _route_match(kind, pattern, path):
    """路由匹配：exact/regex/suffix 返回 Match 对象或 None。"""
    if kind == "exact":
        return _re.fullmatch(_re.escape(pattern), path)
    elif kind == "regex":
        return _re.fullmatch(pattern, path)
    elif kind == "suffix":
        if path.endswith(pattern):
            return True  # 简单匹配标识
    return None


class H0BaseMixin:
    """H0 HTTP 底座（design D1 表 C H0）。"""

    # 文本类才值得 gzip（图片/字体本身已二进制压缩）；svg mimetypes 给
    # image/*，故按后缀白名单而非 ctype 判断
    _GZIP_EXT = {".js", ".css", ".html", ".htm", ".svg", ".json", ".md", ".txt", ".map"}
    _GZIP_MIN = 860  # 小于阈值的响应不值得压缩

    # ── H1 表驱动路由分派（design D1 表 C H1，task 4.5）────────────────

    def _dispatch_table(self, table, path, query):
        """按表遍历匹配并委派（按注册顺序，精确优先）。"""
        for kind, pattern, handler in table:
            m = _route_match(kind, pattern, path)
            if m is not None:
                handler(self, path, query, m)
                return
        self._error(404, "Not Found")

    def _handle_api(self, path: str, query: dict):
        self._dispatch_table(_API_GET_ROUTES, path, query)

    def _handle_api_post(self, path: str, query: dict):
        self._dispatch_table(_API_POST_ROUTES, path, query)

    def _handle_api_delete(self, path: str, query: dict):
        self._dispatch_table(_API_DELETE_ROUTES, path, query)

    # ── H0 HTTP 底座（原 H0 方法，method body zero-move）─────────────────

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
        # 线程上限（dashboard-connection-limit D6）
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
                self._serve_static(path.lstrip("/"))
        except BrokenPipeError:
            pass
        except Exception as e:  # noqa: BLE001
            try:
                self._error(500, f"Internal Server Error: {e}")
            except Exception:
                pass

    def _read_json_body(self) -> dict:
        """读取并解析 JSON 请求体，做大小限制。"""
        from core.dashboard import server as _server_mod
        max_body = getattr(_server_mod, "MAX_POST_BODY", 256 * 1024)
        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            self._error(400, "Invalid Content-Length")
            return None
        if content_length <= 0:
            self._error(400, "Empty request body")
            return None
        if content_length > max_body:
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

    def _wants_gzip(self) -> bool:
        return "gzip" in self.headers.get("Accept-Encoding", "").lower()

    def _maybe_gzip(self, body: bytes) -> bytes:
        if len(body) >= self._GZIP_MIN and self._wants_gzip():
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
            return gzip.compress(body, 5)
        return body

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
        body = json.dumps({"error": msg}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
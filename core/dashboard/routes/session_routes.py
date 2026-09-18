"""session_routes.py — H_SessionRoutesMixin（dashboard-live-session D3）。

项目级自由会话 REST 端点，沿用既有的 mixin + 表驱动路由模式。
"""

from __future__ import annotations

import json
from pathlib import Path


class H_SessionRoutesMixin:
    """H_SessionRoutesMixin：会话 REST 端点。"""

    def _api_session_start(self, query):
        """POST /api/session/start?project=<name> → 创建（或复用存活）会话。

        这是唯一允许启动会话进程的端点。
        返回 {"session": {"id": sid, "started_at": ...}}
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return

        from core.dashboard.session_manager import SessionManager
        sm: SessionManager = self.server.session_manager
        if sm is None:
            self._error(500, "session manager not initialized")
            return

        try:
            session = sm.start(project["name"], project["path"])
        except Exception as exc:
            self._error(500, f"failed to start session: {exc}")
            return

        self._json({
            "session": {
                "id": session.session_id,
                "started_at": session.last_activity,
            }
        })

    def _api_session_get(self, query):
        """GET /api/session?project=<name> → 会话状态 + 全量事件缓冲（只读）。

        无会话时返回 {"session": null, "events": [], "truncated": false}
        MUST NOT 借回读端点启动进程。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return

        from core.dashboard.session_manager import SessionManager
        sm: SessionManager = self.server.session_manager
        if sm is None:
            self._error(500, "session manager not initialized")
            return

        session = sm.get(project["name"])
        if session is None:
            self._json({"session": None, "events": [], "truncated": False})
            return

        events = list(session.events)
        from core.dashboard.session_manager import SESSION_EVENT_BUFFER
        truncated = len(events) >= SESSION_EVENT_BUFFER
        self._json({
            "session": {
                "id": session.session_id,
                "started_at": session.last_activity,
            },
            "events": events,
            "truncated": truncated,
        })

    def _api_session_send(self, query):
        """POST /api/session/send?project=<name> → body {"text": "..."} 发送用户文本。

        空/空白 → 400；项目或会话缺失 → 404；成功 → {"ok": true}
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return

        from core.dashboard.session_manager import SessionManager
        sm: SessionManager = self.server.session_manager
        if sm is None:
            self._error(500, "session manager not initialized")
            return

        session = sm.get(project["name"])
        if session is None:
            self._error(404, "session not found; POST /api/session/start first")
            return

        try:
            body = self._read_json_body()
        except Exception:
            return
        if body is None:
            return  # _read_json_body 已写错误响应

        text = (body.get("text") or "").strip() if isinstance(body, dict) else ""
        if not text:
            self._error(400, "text is required and must not be blank")
            return

        try:
            sm.send(session.session_id, text)
        except Exception as exc:
            self._error(400, f"send failed: {exc}")
            return

        self._json({"ok": True})

    def _api_session_stop(self, query):
        """POST /api/session/stop?project=<name> → 终止会话（幂等）。

        无会话时亦 200。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return

        from core.dashboard.session_manager import SessionManager
        sm: SessionManager = self.server.session_manager
        if sm is None:
            self._error(500, "session manager not initialized")
            return

        session = sm.get(project["name"])
        if session is None:
            self._json({"ok": True})
            return

        try:
            sm.stop(session.session_id, "user")
        except Exception:
            pass  # stop 幂等，异常不影响返回

        self._json({"ok": True})

    def _api_session_watch(self, query, watch):
        """POST/DELETE /api/session/watch?project=<name>&cid=<cid>。

        hub.watch(cid, sid) 或 hub.unwatch(cid, sid)。"""
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return

        from core.dashboard.session_manager import SessionManager
        sm: SessionManager = self.server.session_manager
        if sm is None:
            self._error(500, "session manager not initialized")
            return

        session = sm.get(project["name"])
        if session is None:
            self._error(404, "session not found")
            return

        cid = query.get("cid", [None])[0]
        if not cid:
            self._error(400, "missing cid parameter")
            return

        if watch:
            self.server.sse_hub.watch(cid, session.session_id)
        else:
            self.server.sse_hub.unwatch(cid, session.session_id)

        self._json({"ok": True})

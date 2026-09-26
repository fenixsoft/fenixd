"""run_routes.py — H4 run/events/hooks-audit。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.dashboard import data as dashboard_data
from core.dashboard.registry import Registry

logger = logging.getLogger("fenixd.dashboard.run_routes")


class H4RunRoutesMixin:
    """H4 run/events/hooks-audit。"""

    def _coded_error(self, status: int, msg: str, code: str) -> None:
        """带稳定机器可读 ``code`` 的错误响应（code-review item
        813aa61cb08f）：前端控制流按业务错误码分支，不依赖中文消息子串。
        先例：H12 regression / code_review mixin 同名 helper。"""
        self._json({"error": msg, "code": code}, status)

    def _api_run_cancel(self, query):
        """POST /api/run-cancel?project=<name>&run_id=<id>（可选 reason）

        run 人工取消：写入 .fenix/cancel_run_request.json 文件信号，由 daemon
        主循环下一轮拾取并调 agent_runner.cancel_run。
        - project 不存在 → 404
        - run_id 缺失 → 400
        - 已有未消费请求 → 409（code=cancel_run_request_pending）
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
        # [fenix-ignore:4e54263f454d] 此处不读 body 不会毒化 keep-alive：未消费 body 由 _handle_inner finally 的 _drain_remaining_request_body 统一排空（BUG-01/265e22d75797），同 regression_routes 6e9597e51e90 先例
        if content_length > 0 and not reason:
            body = self._read_json_body()
            if isinstance(body, dict):
                reason = (body.get("reason") or "").strip() or None
        # 归一为 strip 后字符串；None/空白一律落空串（下游按空串视为未提供）
        reason = (reason or "").strip()

        proot = Path(project["path"])
        try:
            result = dashboard_data.request_run_cancel(proot, run_id, reason)
        except Exception as e:  # noqa: BLE001 兜底：写文件异常不崩溃进程
            # 不外泄裸异常文本（code-review item 61849e41918d）：底层原子写
            # 可抛 OSError，str(e) 可能携带服务器内部路径/errno 细节，与
            # project_routes 泛化文案策略同款——细节降级经服务端日志留痕，
            # 客户端收固定文案。
            logger.warning(
                "写入 run 取消请求异常（project=%s run_id=%s）: %s: %s",
                project["name"],
                run_id,
                type(e).__name__,
                e,
            )
            self._error(500, "写入取消请求失败")
            return
        if result.get("missing_run_id"):
            self._error(400, "run_id required")
            return
        if result.get("conflict"):
            self._coded_error(
                409, result.get("error") or "已有进行中的取消请求", "cancel_run_request_pending"
            )
            return
        self._json(
            {
                "requested": True,
                "project": project["name"],
                "run_id": run_id,
                "created": result.get("created"),
            }
        )


    def _api_run(self, run_id: str, query) -> dict:
        project = self._project_from_query(query)
        if project is None:
            return {"error": "unknown project"}
        if not project.get("exists"):
            return {"error": "project not found"}
        try:
            tail = max(1, min(int(query.get("tail", ["300"])[0]), 2000))
        except (TypeError, ValueError):
            tail = 300
        # 向前分页窗口（add-run-record-readability 4.2）：缺省 0 = 既有尾部截取
        try:
            offset_from_end = max(int(query.get("offset_from_end", ["0"])[0]), 0)
        except (TypeError, ValueError):
            offset_from_end = 0
        run = dashboard_data.get_run_events(
            Path(project["path"]), run_id, tail=tail, offset_from_end=offset_from_end
        )
        run["project"] = project["name"]
        return run


    def _api_run_watch(self, run_id: str, query, watch: bool) -> dict:
        """注册/取消某条 SSE 连接的 run 增量订阅（弹窗打开/关闭时调用）。"""
        # 最小防御（code-review item 9d6e8392b667）：空 run_id 会静默注册成
        # 无效订阅（broadcast 按 run_id 精确匹配永远落空），直接拒绝
        if not run_id:
            return {"error": "missing run id"}
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
        records = read_hook_audit(Path(project["path"]), spec=(spec or None), limit=limit)
        return {"project": project["name"], "audit": records}

    # ── agent 提示词（add-agent-prompt-files 任务 3.1）────────────────


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
        - daemon 未受托管（unmanaged）→ 409；未运行（daemon_down）→ 400
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
            if body is None:
                # _read_json_body 失败路径已自行 _error(400/413)，必须终止，
                # 否则继续执行会向同一 keep-alive 连接写第二个响应（与
                # spec_routes _api_admin_invoke 等可选 body 端点的使用惯例对齐）
                return
            # [fenix-ignore:f3dc8a69f935] 非 dict body 在 _read_json_body（base.py）已统一 400「Request body must be a JSON object」并返回 None，此分支 isinstance 恒真，条目所称「非 dict 静默忽略」不存在，口径本就一致
            if isinstance(body, dict):
                # 类型防线（code-review item bc36b94afa48，对齐 _api_session_send
                # b82e10346495 先例）：数字/布尔/dict/list 等非字符串真值直接
                # 400 参数错误，而非 .strip() 抛 AttributeError 被 _handle_inner
                # 兜成 500；缺省（键不存在/None）仍按未提供处理。
                body_reason = body.get("reason")
                if body_reason is not None and not isinstance(body_reason, str):
                    self._error(400, "reason must be a string")
                    return
                reason = (body_reason or "").strip() or None
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
        # unmanaged/daemon_down 前置拒绝（code-review item 9f60357d2f7e）：
        # 数据层此时不写信号直接拒绝（宁拒勿假受理），若落进末尾无条件 200
        # 用户会误以为取消已受理而信号永不消费；口径对齐 regression_routes
        # 同类守卫（unmanaged → 409、stopped → 400），error 文案透传数据层
        if result.get("unmanaged"):
            self._error(
                409,
                result.get("error")
                or "本项目 daemon 未受 supervisor 托管，取消信号不会被消费",
            )
            return
        if result.get("daemon_down"):
            self._error(400, result.get("error") or "daemon 未运行，请先启动 daemon")
            return
        if not result.get("ok"):
            # 兜底：数据层其余拒绝态一律不假受理（仅 ok:True 才回 requested）
            self._error(500, result.get("error") or "写入取消请求失败")
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
        # [fenix-ignore:ab3e32e09872] 200+error 字典系前端依赖的既有契约：request 层仅在非 2xx 才抛 ApiError，200 体按 RunDetail 透传（error 为类型内字段），改 404 需 request 层/组件联动评估，信息级口径差异不值当
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
        # 项目缺失也保留 project 键（code-review item dc93a93c68d9）：与
        # _api_hooks_audit 的 {"project": None, ...} 形状对齐，消费方统一按
        # result.project 读取拿到 null 而非 undefined
        if project is None:
            return {"project": None, "events": []}
        if not project.get("exists"):
            return {"project": None, "events": []}
        try:
            minutes = int(query.get("minutes", ["10"])[0])
        except (TypeError, ValueError):
            minutes = 10
        # 边界夹取与 _api_run tail / _api_hooks_audit limit 的防御口径对齐
        # （code-review item d02a01a1dfcc）：负值会让 cutoff 落到未来、
        # get_recent_events 恒返回空列表且无报错；上界 1440（1 天窗口）—
        # get_recent_events 只读日志尾部 ≤1MB 窗口，更大值仅有截断语义
        minutes = max(1, min(minutes, 1440))
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

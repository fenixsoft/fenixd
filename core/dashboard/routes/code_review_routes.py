"""code_review_routes.py — code-review（周期性代码审查）routes（add-code-review-agent-and-quality-tab）。

承载 5 个端点：
- GET  /api/code-review/items      （query project、可选 status）→ 台账列表
- GET  /api/code-review/progress   （query project）→ 运行进度
- POST /api/code-review/run        （body {project, scope}）→ 写手动触发信号
- POST /api/code-review/generate-spec（body {project, item_ids}）→ 生成修复 SPEC
- POST /api/code-review/items/status（body {project, item_id, status}）→ 人工状态流转

端点 handler 走既有 mixin 形态（self._json / self._error / _read_json_body）。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.dashboard import data as dashboard_data

# 手动触发信号文件（daemon 主循环经 fenixd._check_code_review_requests 消费）。
# 与 admin_invoke_request / cancel_run_request / approve_push_request 同属
# 「dashboard 原子写 → daemon 主循环消费」文件信号族。
CODE_REVIEW_REQUEST = ".fenix/code_review_request.json"


class H11CodeReviewRoutesMixin:
    """H11 code-review（design D1 表 C H11）。"""

    def _api_code_review_items(self, query):
        """GET /api/code-review/items?project=<name>[&status=open,in_spec]

        返回 ``{items: [...]}``（按 severity 排序，默认仅 open）。缺项目 → 404。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        statuses = None
        raw = query.get("status", [None])[0]
        if raw:
            statuses = [s.strip() for s in raw.split(",") if s.strip()]
        items = dashboard_data.read_code_review_items(str(project["path"]), statuses=statuses)
        self._json({"items": items})

    def _api_code_review_progress(self, query):
        """GET /api/code-review/progress?project=<name>

        返回 ``{running, review_id, review_kind, total, done, current}``。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        self._json(dashboard_data.read_code_review_progress(str(project["path"])))

    def _api_code_review_run(self, query):
        """POST /api/code-review/run — body {project, scope: "full"|"window"}

        写 ``.fenix/code_review_request.json`` 文件信号 → daemon 主循环消费
        （不直接同步跑审查）。

        - 项目不存在 → 404
        - 已有审查在跑（progress.running）→ 409「已有审查在进行中」
        - 消费方守卫：daemon 未受 supervisor 托管（hosting_state ==
          "unmanaged"）→ 409 明确拒绝（对齐 request_spec_approve_push——
          信号无人消费会永久滞留并在 daemon 下次启动时被消费成一次用户并未
          请求的审查）；stopped → 400「daemon 未运行」。
        - 受理 → 200 + {ok, scope, requested_at}
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        body = self._read_json_body()
        if body is None:
            return
        scope = body.get("scope") or "window"
        if scope not in ("full", "window"):
            self._error(400, f"非法 scope（应为 full 或 window）: {scope!r}")
            return
        proot = Path(project["path"])

        # 运行中守卫（基于产物终态判定，见 core.code_review.read_progress——
        # 已取消/已停机的 run 必须判 running=false，否则 409 恒真锁死后续触发）
        progress = dashboard_data.read_code_review_progress(str(proot))
        if progress.get("running"):
            self._error(409, "已有审查在进行中")
            return

        # 消费方守卫（hosting_state 判据，先例 request_spec_approve_push）
        from core.fenix_session import hosting_state as _hosting_state

        try:
            state = _hosting_state(str(proot))
        except Exception:
            state = "stopped"  # 判定异常按未运行兜底，宁拒勿假放行
        if state == "unmanaged":
            self._error(
                409,
                "本项目 daemon 未受 supervisor 托管，审查信号不会被消费。"
                "经项目页「安装托管」或 /fenix-setup 恢复 supervisor 托管后重试",
            )
            return
        if state != "managed":
            self._error(400, "daemon 未运行，请先启动 daemon")
            return

        # 原子写信号文件（tmp+rename + fsync，与 request_admin_invoke 同构）
        created = datetime.now(timezone.utc).isoformat()
        payload = {"scope": scope, "source": "dashboard", "created": created}
        req_path = proot / CODE_REVIEW_REQUEST
        if req_path.exists():
            self._error(409, "已有未消费的审查触发请求（请稍后重试）")
            return
        req_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(req_path.parent), prefix=".code_review_request.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, req_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            self._error(500, "审查触发信号写入失败")
            return
        self._json({"ok": True, "scope": scope, "requested_at": created})

    def _api_code_review_generate_spec(self, query):
        """POST /api/code-review/generate-spec — body {project, item_ids: [...]}

        body 可选 ``start_after``（三态，与 `set_spec_start_after` 同源口径）：
        - 缺省 / null / 空串 → 立即执行
        - ``"manual"`` → 待激活（哨兵，永不到期）
        - ISO8601 → 定时拾取
        非法值 400（不落盘、条目状态不变）。

        调 ``core.code_review.generate_fix_spec`` 把选中问题机械合成修复 SPEC。

        返回 ``{ok, spec_name, skipped, error, start_after}``；成功把条目置 in_spec。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        body = self._read_json_body()
        if body is None:
            return
        item_ids = body.get("item_ids")
        if not isinstance(item_ids, list) or not all(isinstance(i, str) for i in item_ids):
            self._error(400, "item_ids 必须为字符串数组")
            return
        if not item_ids:
            self._error(400, "item_ids 不能为空")
            return
        from core.code_review import _normalize_start_after, generate_fix_spec

        start_after = body.get("start_after")
        ok_sa, normalized_sa, sa_err = _normalize_start_after(start_after)
        if not ok_sa:
            self._error(400, sa_err)
            return

        proot = Path(project["path"])
        try:
            result = generate_fix_spec(
                str(proot), self._code_review_state_machine(), item_ids, normalized_sa
            )
        except Exception as e:  # noqa: BLE001 —— 端点不因内部异常 500 崩溃
            self._error(500, f"生成修复 SPEC 失败: {e}")
            return
        if not result.get("ok"):
            self._error(400, result.get("error") or "生成修复 SPEC 失败")
            return
        self._json(result)

    def _api_code_review_items_status(self, query):
        """POST /api/code-review/items/status — body {project, item_id, status}

        人工状态流转（ignored 忽略 / open 清除归属），经
        ``core.code_review.set_item_status``（仅 open/ignored 可人工置入）。

        返回 ``{ok, item_id, status, error}``。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        body = self._read_json_body()
        if body is None:
            return
        item_id = body.get("item_id")
        status = body.get("status")
        if not isinstance(item_id, str) or not item_id:
            self._error(400, "item_id required")
            return
        if status not in ("open", "ignored"):
            self._error(400, f"status 仅支持 open/ignored（人工可置状态）: {status!r}")
            return
        from core.code_review import set_item_status

        proot = Path(project["path"])
        try:
            result = set_item_status(str(proot), item_id, status)
        except Exception as e:  # noqa: BLE001
            self._error(500, f"状态流转失败: {e}")
            return
        if not result.get("ok"):
            self._error(400, result.get("error") or "状态流转失败")
            return
        self._json(result)

    # ── 辅助 ──────────────────────────────────────────────

    @staticmethod
    def _code_review_state_machine():
        """框架根 StateMachine（generate_fix_spec 注册用；惰性构造，无缓存需求）。"""
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        from core.state_machine import StateMachine

        return StateMachine(_server_mod.FRAMEWORK_ROOT / ".fenix" / "STATE.md", None)
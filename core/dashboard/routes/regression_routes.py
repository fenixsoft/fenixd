"""regression_routes.py — 全量回归 (test-regression-tab) routes（add-test-regression-tab）。

承载 2 个端点：
- GET  /api/regression/result （query project）→ 最近一次回归快照
- POST /api/regression/run    （body {project}）→ 写手动触发信号

端点 handler 走既有 mixin 形态（self._json / self._error / _read_json_body）。
手动触发走 code-review 同款「dashboard 原子写 → daemon 主循环消费」范式：
POST 只写 ``.fenix/regression_request.json`` 文件信号，MUST NOT 在 HTTP
线程内同步跑回归（回归可跑 1800s）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from core.dashboard import data as dashboard_data

# 手动触发信号文件（daemon 主循环经 fenixd._check_regression_requests 消费）。
# 与 code_review_request / approve_push_request 同属「dashboard 原子写 →
# daemon 主循环消费」文件信号族。
REGRESSION_REQUEST = ".fenix/regression_request.json"


class H12RegressionRoutesMixin:
    """H12 regression（design 表 C H12）。"""

    def _api_regression_result(self, query):
        """GET /api/regression/result?project=<name>

        返回 ``.fenix/regression/last-run.json`` 快照全字段（200）；快照缺失 →
        ``{status: "never_run"}``（200）；快照损坏 → ``{status: "parse_error",
        reason}``（200）。项目不存在 → 404。MUST NOT 因快照问题抛 500。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        self._json(dashboard_data.read_regression_result(str(project["path"])))

    def _api_regression_run(self, query):
        """POST /api/regression/run — body {project}

        写 ``.fenix/regression_request.json`` 文件信号 → daemon 主循环消费
        （不直接同步跑回归）。

        - 项目不存在 → 404
        - 项目 verify.yaml 无有效 regression 段 → 400「该项目未配置全量回归」
          （MUST NOT 派发空跑）
        - 已有回归在跑（单飞）→ 409「已有回归在进行中」（基于既有运行中判定）
        - 消费方守卫：daemon 未受 supervisor 托管（hosting_state ==
          "unmanaged"）→ 409 明确拒绝；stopped → 400「daemon 未运行」
        - 受理 → 200 + {ok, requested_at}
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        body = self._read_json_body()
        if body is None:
            return
        proot = Path(project["path"])

        # 项目未配置回归守卫（verify.yaml regression 段缺失/无效 → 400）
        from core.verify_contract import load_verify_contract

        contract = load_verify_contract(proot, logger=getattr(self, "logger", None))
        if contract is None or contract.regression is None:
            self._error(400, "该项目未配置全量回归（verify.yaml regression 段）")
            return

        # 运行中守卫（已有回归在跑 → 409，单飞不并发；基于 marker 新鲜度
        # 判定，与 code_review 的 progress.running 同义——marker 不存在
        # 或超窗 stale 即视为未运行）
        if dashboard_data.is_regression_running(proot):
            self._error(409, "已有回归在进行中")
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
                "本项目 daemon 未受 supervisor 托管，回归信号不会被消费。"
                "经项目页「安装托管」或 /fenix-setup 恢复 supervisor 托管后重试",
            )
            return
        if state != "managed":
            self._error(400, "daemon 未运行，请先启动 daemon")
            return

        # 原子创建信号文件（O_CREAT|O_EXCL 独占创建，对齐 code-review）：
        # ThreadingHTTPServer 并发线程下非原子 exists 检查会互相覆盖信号，
        # 独占创建成功即胜出；FileExistsError → 409（已有未消费请求）。
        created = datetime.now(timezone.utc).isoformat()
        payload = {"source": "dashboard", "created": created}
        req_path = proot / REGRESSION_REQUEST
        req_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(req_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            self._error(409, "已有未消费的回归触发请求（请稍后重试）")
            return
        except OSError:
            self._error(500, "回归触发信号写入失败")
            return
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            # 写中途失败：清掉半写文件，避免残留被 daemon 误消费
            try:
                os.unlink(str(req_path))
            except OSError:
                pass
            self._error(500, "回归触发信号写入失败")
            return
        self._json({"ok": True, "requested_at": created})
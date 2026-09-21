"""regression_routes.py — 全量回归 (test-regression-tab) routes（add-test-regression-tab）。

承载 4 个端点：
- GET  /api/regression/result    （query project）→ 最近一次回归快照
- GET  /api/regression/config    （query project）→ verify.yaml regression 段配置状态
- POST /api/regression/run       （body {project}）→ 写手动触发信号
- POST /api/regression/autodraft （body {project}）→ 写 AI 补 regression 段信号

端点 handler 走既有 mixin 形态（self._json / self._error / _read_json_body）。
手动触发走 code-review 同款「dashboard 原子写 → daemon 主循环消费」范式：
POST 只写 ``.fenix/regression_request.json`` 文件信号，MUST NOT 在 HTTP
线程内同步跑回归（回归可跑 1800s）。

autodraft 走 AdminStore 的 kind=SIGNAL 通道（同 verify-yaml-autodraft）：
写信号 → admin_monitor 巡检摄取 → 唤起 Administrator 补段（分钟级）。
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


def _evidence_project(evidence: str) -> str:
    """从 evidence 串（``项目名=<name>; ...``）按字段解析项目名，全等比较用。

    与 settings_routes 的同名内联 helper 同口径：项目名互为前缀时不误判
    （``项目名=proj`` 不得命中 ``项目名=proj2; ...``）。
    """
    for seg in (evidence or "").split(";"):
        seg = seg.strip()
        if seg.startswith("项目名="):
            return seg[len("项目名="):].strip()
    return ""


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

    def _api_regression_config(self, query):
        """GET /api/regression/config?project=<name>

        返回项目 ``.fenix/verify.yaml`` 的 regression 段解析状态（权威判定走
        ``load_verify_contract``，与周期检查点 / 手动触发的口径完全一致）：

        - ``exists``：verify.yaml 文件是否存在
        - ``contract_valid``：契约文件存在且可解析（``load_verify_contract`` 非 None）
        - ``regression``：有效 regression 段的字段映射；无段 / 整段无效 → ``null``

        设置页「质量」页签据 ``regression`` 是否为空展示段配置 / 缺失提示，
        并提供「使用 AI 生成」按钮。项目不存在 → 404。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])
        from core.verify_contract import load_verify_contract

        contract = load_verify_contract(proot, logger=getattr(self, "logger", None))
        exists = (proot / ".fenix" / "verify.yaml").is_file()
        regression = None
        if contract is not None and contract.regression is not None:
            spec = contract.regression
            regression = {
                "cmd": spec.cmd,
                "output": spec.output,
                "timeout_seconds": spec.timeout_seconds,
                "format": spec.format,
                "long_test_threshold_seconds": spec.long_test_threshold_seconds,
            }
        self._json(
            {
                "project": project["name"],
                "exists": exists,
                "contract_valid": contract is not None,
                "regression": regression,
            }
        )

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

    def _api_regression_autodraft_post(self, query):
        """POST /api/regression/autodraft — body {project}

        触发 AI 补写 regression 段（设置页「质量」页签回归卡片「使用 AI 生成」）。
        只补段、不重整契约，按契约状态分流（判定走 ``load_verify_contract``）：

        - 契约缺失（``contract is None``）→ 写 ``verify_contract_missing``
          信号（Administrator 起草完整契约；有测试体系时手册要求一并生成
          regression 段）→ ``dispatched``
        - 契约有效但无有效 regression 段 → 写 ``verify_regression_missing``
          信号（Administrator 仅补段，MUST NOT 动 prepare/serve/ready）→ ``dispatched``
        - 契约有效且已有有效 regression 段 → ``skipped``（无需补写，Administrator
          按「有效配置一律不碰」边界不跑）

        信号走 AdminStore kind=SIGNAL 通道（同 verify-yaml-autodraft）→
        admin_monitor 巡检摄取唤起 Administrator（分钟级）。写前同项目同类型
        在途去重（未 escalated 且未 handled 的同类信号已存在 → 不重复写，仍回
        ``dispatched`` 并注明已有在途请求）。
        """
        body = self._read_json_body()
        if body is None:
            return
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])

        from core.admin_store import AdminStore, SIGNAL
        from core.verify_contract import load_verify_contract

        contract = load_verify_contract(proot, logger=getattr(self, "logger", None))

        # 已有有效 regression 段 → 不补写（人工/既有配置权威；避免无谓唤起 admin run）
        if contract is not None and contract.regression is not None:
            self._json(
                {
                    "ok": True,
                    "project": project["name"],
                    "status": "skipped",
                    "message": "regression 段已配置，无需补写。如需调整请在「项目简介」面板编辑 verify.yaml。",
                }
            )
            return

        # 契约缺失 → 起草完整契约（含 regression 段）；契约有效缺段 → 仅补段
        signal_type = (
            "verify_contract_missing" if contract is None else "verify_regression_missing"
        )
        store = AdminStore(proot, logger=None)
        evidence_detail = f"项目名={project['name']}"

        # 在途去重（对齐 settings_routes 的 verify-yaml-autodraft）：同项目同类型、
        # 未被巡检摄取（not escalated）且未 handled 的信号已存在 → 不重复写。
        inflight = [
            r
            for r in store.read_all()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == signal_type
            and not r.get("handled")
            and not r.get("escalated")
            and _evidence_project(r.get("evidence")) == project["name"]
        ]
        if inflight:
            self._json(
                {
                    "ok": True,
                    "project": project["name"],
                    "status": "dispatched",
                    "message": "已有在途的回归段补写请求，无需重复触发；Administrator 将在下一轮巡检拾取（数分钟内），结果见运维记录。",
                }
            )
            return

        store.append(
            {
                "kind": SIGNAL,
                "signal_type": signal_type,
                "spec": None,
                "severity": "major",
                "description": "AI 补写 regression 段请求（UI 手动触发）",
                "evidence": evidence_detail,
                "source": "ui-manual",
                "recommended_action": "Administrator 将在下一轮巡检拾取（数分钟内），结果见运维记录；完成后可点「刷新」查看 verify.yaml 的 regression 段。",
            }
        )
        self._json(
            {
                "ok": True,
                "project": project["name"],
                "status": "dispatched",
                "message": "已提交 AI 补写 regression 段请求，Administrator 将在下一轮巡检拾取（数分钟内），结果见运维记录。",
            }
        )
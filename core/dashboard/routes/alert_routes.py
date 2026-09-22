"""alert_routes.py — H6 alerts/admin-activities。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin。
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.dashboard import data as dashboard_data

logger = logging.getLogger("fenixd.dashboard.alert_routes")


class H6AlertRoutesMixin:
    """H6 alerts/admin-activities。"""

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
            if p.get("fixture"):
                continue  # fixture-project-governance：夹具项目告警为验证噪音，不进人工聚合
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
        all_resolved.sort(key=lambda a: a.get("handled_at") or a.get("created") or "", reverse=True)
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
                "activities": dashboard_data.get_admin_activities(proot, spec=spec_name),
            }

        projects_out = []
        for p in self.server.projects():
            if p.get("fixture"):
                continue  # fixture-project-governance：夹具项目处置记录不进人工聚合视图
            if not p.get("exists"):
                continue
            acts = dashboard_data.get_admin_activities(Path(p["path"]), spec=spec_name)
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
            self.server.sse_hub.broadcast(
                {
                    "project": project["name"],
                    "type": "alerts",
                    "summary": dashboard_data.alerts_summary(Path(project["path"])),
                }
            )
        except Exception as e:
            # 广播失败留痕（code-review item 95ab3853f55d）：旧 `except: pass`
            # 把（含 payload 形态错误等编程错误的）一切失败静默吞掉，持续失败的
            # 广播无迹可查。降级为 WARNING 不阻断已成功的处置动作。
            logger.warning("SSE 广播失败（告警已处置，横幅可能滞后）: %s", e)
        self._json({"ok": True, "id": alert_id})


    def _api_alert_resolve(self, query) -> dict:
        """POST /api/alert-resolve — 人工裁决一次选择完成处置闭环（4.1）。

        body ``{project, alert_id, choice_id, note?}``。按序：
        (1) 校验告警存在且未 handled，按 alert ``signal_type`` 从注册表校验
        ``choice_id`` 合法（记录内 choices 优先，缺失回退注册表）；(2) 执行
        choice 映射动作（``execute_adjudication_choice`` 共享执行器）；(3)
        标记告警 handled（ESCALATION 走 ``mark_handled``，SIGNAL 走
        ``mark_signal_handled``）并落 DISPOSITION 处置留痕（choice_id/note/
        动作步骤摘要）；(4) SSE 广播刷新横幅。

        任一步失败返回结构化错误且不标记 handled；已执行的前序动作在错误
        信息中如实报告（不做虚假回滚声明）。
        """
        project_name = (query.get("project", [None])[0]) or None
        body = self._read_json_body()
        if body is None:
            return
        alert_id = str(body.get("alert_id") or "").strip()
        choice_id = str(body.get("choice_id") or "").strip()
        note = str(body.get("note") or "")
        if not project_name:
            project_name = str(body.get("project") or "").strip()
        if not project_name:
            self._error(400, "missing project")
            return
        project = self.server.project_by_name(project_name)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        if not alert_id or not choice_id:
            self._error(400, "alert_id and choice_id are required")
            return
        proot = Path(project["path"])

        from core.admin_store import AdminStore, DISPOSITION, SIGNAL
        from core.dashboard.data.adjudication_choices import (
            choices_for,
            is_adjudicable,
        )

        store = AdminStore(proot, logger)
        alert = next((r for r in store.read_all() if r.get("id") == alert_id), None)
        if alert is None:
            self._error(404, "alert not found")
            return
        if alert.get("handled"):
            self._error(409, "alert already handled（不重复执行动作）")
            return

        signal_type = str(alert.get("signal_type") or "")
        spec = str(alert.get("spec") or "")
        # choice 合法性：记录内 choices 优先（发射点快照），缺失回退注册表
        record_choices = alert.get("choices") or choices_for(signal_type)
        valid_ids = [c.get("id") for c in record_choices if isinstance(c, dict)]
        if is_adjudicable(signal_type) and choice_id not in valid_ids:
            legal = "、".join(
                f"{c.get('id')}({c.get('label')})"
                for c in record_choices
                if isinstance(c, dict)
            )
            self._error(400, f"非法 choice_id '{choice_id}'，该信号合法选项：{legal}")
            return

        # 执行映射动作（共享执行器：与 Administrator 处置消费同一路径）
        try:
            result = dashboard_data.execute_adjudication_choice(
                proot, spec, choice_id, note=note, signal_type=signal_type
            )
        except Exception as e:  # 动作执行异常：不标记 handled，如实报告
            logger.exception("alert-resolve 动作执行异常 alert=%s", alert_id)
            self._error(500, f"动作执行异常: {e}（告警保持未处理，可重试裁决）")
            return
        steps = result.get("steps") or []
        if not result.get("ok"):
            self._error(
                400,
                f"{result.get('error') or '动作未成功执行'}"
                + (f"（已执行步骤：{'；'.join(steps)}）" if steps else "")
                + "（告警保持未处理，可调整后重试）",
            )
            return

        # handled 标记：kind 差异约定（ESCALATION→mark_handled，
        # SIGNAL→mark_signal_handled 直接更新 handled 字段）
        marked = (
            store.mark_signal_handled(alert_id)
            if alert.get("kind") == SIGNAL
            else store.mark_handled(alert_id)
        )

        # 处置留痕：DISPOSITION 记录（choice_id/note/动作步骤摘要，
        # 对 dashboard admin 活动区可见，作为裁决审计轨迹）
        try:
            store.append(
                {
                    "kind": DISPOSITION,
                    "signal_type": signal_type or None,
                    "spec": spec or None,
                    "severity": alert.get("severity"),
                    "description": alert.get("description"),
                    "action_taken": "；".join(steps),
                    "result": "success",
                    "recommended_action": "",
                    "summary": f"人工裁决 {choice_id}（{result.get('action')}）"
                    + (f"：{note}" if note else ""),
                    "choice_id": choice_id,
                    "note": note,
                    "source": "alert-resolve",
                    "error": "",
                }
            )
        except Exception as e:
            # 留痕失败不回滚已执行的动作与 handled 标记，如实告知
            logger.warning("alert-resolve 处置留痕写入失败 alert=%s: %s", alert_id, e)

        try:
            self.server.sse_hub.broadcast(
                {
                    "project": project["name"],
                    "type": "alerts",
                    "summary": dashboard_data.alerts_summary(proot),
                }
            )
        except Exception as e:
            logger.warning("SSE 广播失败（告警已处置，横幅可能滞后）: %s", e)
        self._json(
            {
                "ok": True,
                "id": alert_id,
                "choice_id": choice_id,
                "action": result.get("action"),
                "steps": steps,
                "marked": bool(marked),
                "note": note,
            }
        )

    def _api_alerts_clear(self):
        """清理所有事件：把全部项目未处理升级告警标记为已处理；逐项目广播刷新横幅。

        与 `_api_alerts` / `_api_admin_activities` 一致地**跳过 fixture 项目**
        （code-review item cb7a35748089）：夹具告警为验证噪音、本就不进人工聚合
        视图，但旧实现仍对其 mark_all_alerts_handled 并广播其摘要——用户「清理
        可见横幅」会静默改写隐藏的夹具状态，且破坏夹具 reset 契约（夹具告警
        只应经 bin/fixture_scheduling_showcase.py --reset 复位）。
        """
        cleared = 0
        for p in self.server.projects():
            if p.get("fixture"):
                continue  # fixture-project-governance：夹具告警只经 --reset 复位
            if not p.get("exists"):
                continue
            proot = Path(p["path"])
            cleared += dashboard_data.mark_all_alerts_handled(proot)
            try:
                self.server.sse_hub.broadcast(
                    {
                        "project": p["name"],
                        "type": "alerts",
                        "summary": dashboard_data.alerts_summary(proot),
                    }
                )
            except Exception as e:
                # 广播失败留痕（code-review item 95ab3853f55d），同 _api_alert_handled。
                logger.warning(
                    "SSE 广播失败（告警已清理，横幅可能滞后）: %s", e
                )
        self._json({"ok": True, "cleared": cleared})

    # ── 项目管理端点（启停 daemon / 软删除） ──────────────


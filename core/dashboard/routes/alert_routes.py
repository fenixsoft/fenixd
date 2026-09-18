"""alert_routes.py — H6 alerts/admin-activities。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.admin_store import AdminStore, SIGNAL
from core.dashboard import data as dashboard_data
from core.dashboard.registry import Registry


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
        except Exception:
            pass
        self._json({"ok": True, "id": alert_id})


    def _api_alerts_clear(self):
        """清理所有事件：把全部项目未处理升级告警标记为已处理；逐项目广播刷新横幅。"""
        cleared = 0
        for p in self.server.projects():
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
            except Exception:
                pass
        self._json({"ok": True, "cleared": cleared})

    # ── 项目管理端点（启停 daemon / 软删除） ──────────────


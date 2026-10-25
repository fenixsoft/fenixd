"""collab_graph_routes.py — 跨项目角色协作图谱只读端点。

add-collab-graph-bigscreen：``GET /api/overview/collab-graph`` 对 dashboard
托管全部项目的全部 SPEC 聚合角色级协作图谱（roles/edges/kpis + 下钻明细）。
派生逻辑单点在 ``core/dashboard/data/collab_graph.py``（逐 SPEC 复用
``topology.derive_topology``），本 mixin 只做项目寻址/范围收窄与响应组装。

错误契约与 ``/api/specs/<spec>`` detail 同族的有意兼容：``?project`` 指向
未知/不存在项目时返回 200 + ``{"error": ...}`` 字典（同 _api_alerts 注记
——大屏页按 200 消费 error 字典渲染提示，改 404 会翻转成整页错误）。
聚合路径跳过 fixture 项目与不存在项目（``_aggregatable_projects`` 同口径
——夹具项目为验证噪音，不进人工聚合视图）。
"""

import logging
from pathlib import Path

from core.dashboard import data as dashboard_data

# fenixd. 层级字面量（tests/test_logger_no_bypass.py：core/ 禁 __name__ 旁路）
logger = logging.getLogger("fenixd.dashboard.routes.collab_graph_routes")


class H16CollabGraphRoutesMixin:
    """H16 overview collab-graph（只读）。"""

    def _api_overview_collab_graph(self, query) -> dict:
        """GET /api/overview/collab-graph —— 跨项目角色级协作图谱（只读）。

        缺省聚合全部可聚合项目（非 fixture 且 exists）；``?project=<name>``
        收窄到单项目。零副作用：不写任何运行时状态（specs「聚合复用与性能
        边界」Requirement）。
        """
        project_name = query.get("project", [None])[0] or None
        if project_name:
            project = self.server.project_by_name(project_name)
            if project is None or not project.get("exists"):
                # 有意 200 错误体契约（同 _api_alerts / _api_spec_detail 注记）
                return {"error": "project not found", "project": project_name}
            # 显式指定项目即使 fixture 也照常聚合（单项目寻址语义，
            # 与 _api_alerts 的 ?project 分支同口径）
            return dashboard_data.aggregate_collab_graph([project], project=project_name)
        aggregatable = [
            p for p in self.server.projects() if not p.get("fixture") and p.get("exists")
        ]
        return dashboard_data.aggregate_collab_graph(aggregatable)

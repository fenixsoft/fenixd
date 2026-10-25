"""topology_routes.py — H15 SPEC 协作拓扑只读端点（add-spec-topology-bigscreen）。

``GET /api/specs/<spec>/topology``：与 ``/api/specs/<spec>`` detail 同族单键
寻址（regex 路由注册于 routes/base.py ``_API_GET_ROUTES``，复用现有鉴权/sig
与宿主约定）。派生逻辑单点在 ``core/dashboard/data/topology.py``，本 mixin
只做项目/spec 寻址与响应组装，零派生逻辑（前端零拓扑推导的服务端前提）。
"""

import logging
from pathlib import Path

from core.dashboard import data as dashboard_data
from core.dashboard.routes.spec_routes import _internal_error, _spec_entry_with_archive_fallback

# fenixd. 层级字面量（tests/test_logger_no_bypass.py：core/ 禁 __name__ 旁路）
logger = logging.getLogger("fenixd.dashboard.routes.topology_routes")


class H15TopologyRoutesMixin:
    """H15 spec topology（只读）。"""

    def _api_spec_topology(self, spec: str, query) -> None:
        """GET /api/specs/<spec>/topology —— SPEC 协作拓扑派生图（只读）。

        自含响应 handler（同 ``_api_spec_doc`` 形态）：成功写 ``_json``、内部
        异常经 ``_internal_error`` 自写 500——适配器 MUST NOT 再包 ``_json``
        双重写响应（keep-alive 下残留第二响应污染下一请求）。

        错误契约与 ``/api/specs/<spec>`` detail 同族的有意兼容：未知/不存在
        项目、spec 未命中维持 200 + ``{"error": ...}``，不走 _error(404) 家族
        （同 _api_spec_detail 注记：大屏页 load() 按 200 消费 error 字典渲染
        提示，改 404 会翻转成整页错误）。
        """
        try:
            project = self._project_from_query(query)
            if project is None:
                self._json({"error": "unknown project"})
                return
            if not project.get("exists"):
                self._json({"error": "project not found"})
                return
            proot = Path(project["path"])
            # 条目已迁出（仅清单有）的已归档 SPEC 继续可读（清单回退）——归档
            # 降级骨架正是本端点的既定行为（specs「归档 SPEC 降级骨架」）
            entry = _spec_entry_with_archive_fallback(proot, spec)
            if entry is None:
                self._json(
                    {"error": f"spec not found: {spec}", "project": project["name"]}
                )
                return
            data = dashboard_data.derive_topology(proot, spec, entry)
            data["project"] = project["name"]
            self._json(data)
        except Exception as exc:  # noqa: BLE001 —— 端点级兜底 500 统一收口
            _internal_error(self, "spec topology failed", exc)

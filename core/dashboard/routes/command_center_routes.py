"""command_center_routes.py — H17 指挥中心只读端点（add-command-center 2.4）。

``GET /api/command-center/{kpi,org,pipeline,ledger,inbox,spec-runs}`` 六个只
读聚合端点：派生逻辑单点在 ``core/dashboard/data/command_center.py``，本
mixin 只做项目寻址/范围收窄与响应组装（data 模块 + routes mixin +
server.py 注册 mixin 的既有同族形态；spec-runs 为 add-command-center-spec-
view 2.2 追加的纯只读新端点，遵守本模块「不新增 POST」约定）。

错误契约与 ``_api_alerts``（alert_routes.py）同族的有意兼容：``?project``
指向未知/不存在项目时返回 200 + ``{"error": ...}`` 字典（大屏页按 200 消费
error 字典渲染提示，改 404 会翻转成整页错误）。聚合路径跳过 fixture 项目
与不存在项目（夹具项目为验证噪音，不进人工聚合视图）。

路由注册：六条目沿用 routes/base.py ``_API_GET_ROUTES`` 表驱动分派链既有
条目形态（exact + 模块级适配函数），在本模块导入时追加进同一张表——
add-command-center 任务 5.2 零改动红线（既有 routes 模块仅 server.py 注册
行新增）要求既有 base.py 保持不动，故条目追加单点落在本新模块（server.py
导入本 mixin 先于 DashboardHandler 类创建与请求分派，追加时序安全；Python
模块缓存保证单次追加，无重复注册）。bin/gen-route-map.py 的表驱动主源扫描
以 base.py 表字面量为界，本模块条目由其 routes/*.py 文本扫描级兜底可见。
"""

import logging

from core.dashboard.data.command_center import (
    ORG_WINDOWS,
    WINDOW_TODAY,
    aggregate_inbox,
    aggregate_kpi,
    aggregate_ledger,
    aggregate_org,
    aggregate_pipeline,
    aggregate_spec_runs,
)
from .base import _API_GET_ROUTES

# fenixd. 层级字面量（tests/test_logger_no_bypass.py：core/ 禁 __name__ 旁路）
logger = logging.getLogger("fenixd.dashboard.routes.command_center_routes")


class H17CommandCenterRoutesMixin:
    """H17 指挥中心（只读六端点：kpi/org/spec-runs/pipeline/ledger/inbox）。"""

    # 六端点共用的项目寻址/范围收窄单点（与 _api_alerts 的 ?project 分支
    # 同口径）：显式 ?project= 单项目寻址（fixture 也照常聚合）；缺省聚合全部
    # 非 fixture 且 exists 的项目。未知/不存在项目返回 200+error 字典。
    # data 层聚合入口按 (registry_projects, project) 注入模式自行收窄数据
    # 范围；registry_projects 传聚合范围全集，使响应 projects 回显保持全集
    # （流水线屏项目筛选下拉数据源，specs「交付流水线派生」Scenario）。
    def _command_center_scope(self, query) -> dict:
        project_name = query.get("project", [None])[0] or None
        aggregatable = [
            p for p in self.server.projects() if not p.get("fixture") and p.get("exists")
        ]
        if project_name:
            project = self.server.project_by_name(project_name)
            if project is None or not project.get("exists"):
                # 有意 200 错误体契约（同 _api_alerts 注记）
                return {
                    "error": {"error": "project not found", "project": project_name}
                }
            if project.get("fixture"):
                # 显式指定项目即使 fixture 也照常聚合（单项目寻址语义，
                # 与 _api_alerts 的 ?project 分支同口径）
                aggregatable = aggregatable + [project]
            return {"projects": aggregatable, "project": project_name}
        return {"projects": aggregatable, "project": None}

    def _api_command_center_kpi(self, query) -> dict:
        """GET /api/command-center/kpi —— KPI 四指标 + 网关配置态（只读）。"""
        scope = self._command_center_scope(query)
        if "error" in scope:
            return scope["error"]
        return aggregate_kpi(scope["projects"], project=scope["project"])

    def _api_command_center_org(self, query) -> dict:
        """GET /api/command-center/org —— 组织网格车道卡 + 产品团队汇总（只读）。

        query: project（可选，单项目筛选）；window（可选，today/7d/all，
        缺省 today；非法值数据层防御性回落 today）。
        """
        scope = self._command_center_scope(query)
        if "error" in scope:
            return scope["error"]
        window = query.get("window", [WINDOW_TODAY])[0] or WINDOW_TODAY
        if window not in ORG_WINDOWS:
            window = WINDOW_TODAY
        return aggregate_org(scope["projects"], project=scope["project"], window=window)

    def _api_command_center_spec_runs(self, query) -> dict:
        """GET /api/command-center/spec-runs —— spec 视图轮次聚合（只读）。

        query: project（**必填**，spec 所属项目）；spec（**必填**，SPEC 名）；
        window（可选 today/7d/all，缺省 today，非法值数据层防御性回落 today）。
        project/spec 缺失或空值同样返回 200+error 字典（与未知项目同族契约），
        MUST NOT 回落跨项目聚合（add-command-center-spec-view 2.2）；未知项目
        寻址复用 :meth:`_command_center_scope` 既有契约。
        """
        project_name = query.get("project", [None])[0] or None
        spec_name = query.get("spec", [None])[0] or None
        if not project_name or not spec_name:
            # 有意 200 错误体契约（必填缺失，不回落跨项目聚合）
            return {
                "error": "project and spec are required",
                "project": project_name,
                "spec": spec_name,
            }
        scope = self._command_center_scope(query)
        if "error" in scope:
            return scope["error"]
        window = query.get("window", [WINDOW_TODAY])[0] or WINDOW_TODAY
        if window not in ORG_WINDOWS:
            window = WINDOW_TODAY
        return aggregate_spec_runs(
            scope["projects"], project_name, spec_name, window=window
        )

    def _api_command_center_pipeline(self, query) -> dict:
        """GET /api/command-center/pipeline —— SPEC 状态五列看板（只读）。"""
        scope = self._command_center_scope(query)
        if "error" in scope:
            return scope["error"]
        return aggregate_pipeline(
            scope["projects"], project=scope["project"]
        )

    def _api_command_center_ledger(self, query) -> dict:
        """GET /api/command-center/ledger —— 跨项目最近 50 条 run 台账（只读）。"""
        scope = self._command_center_scope(query)
        if "error" in scope:
            return scope["error"]
        return aggregate_ledger(
            scope["projects"], project=scope["project"]
        )

    def _api_command_center_inbox(self, query) -> dict:
        """GET /api/command-center/inbox —— 裁决收件箱只读装配（不执行）。

        执行走既有 ``POST /api/alert-resolve``；本端点纯装配，响应不携带任何
        执行动作端点引用。
        """
        scope = self._command_center_scope(query)
        if "error" in scope:
            return scope["error"]
        return aggregate_inbox(
            scope["projects"], project=scope["project"]
        )


# ── GET 路由表适配函数（既有条目形态：模块级 (s, p, q, m) → mixin 方法） ──

def _get_command_center_kpi(s, p, q, m):
    s._json(s._api_command_center_kpi(q))

def _get_command_center_org(s, p, q, m):
    s._json(s._api_command_center_org(q))

def _get_command_center_spec_runs(s, p, q, m):
    s._json(s._api_command_center_spec_runs(q))

def _get_command_center_pipeline(s, p, q, m):
    s._json(s._api_command_center_pipeline(q))

def _get_command_center_ledger(s, p, q, m):
    s._json(s._api_command_center_ledger(q))

def _get_command_center_inbox(s, p, q, m):
    s._json(s._api_command_center_inbox(q))


# 表条目追加（exact 匹配；3 元组无 ETag 签名——读侧按无条件 200，前端 ETag
# 缓存对无签名端点天然降级为普通请求）。本列表对象与 base.py 命名空间共享，
# extend 原地生效（见模块 docstring 注册注记）。
_API_GET_ROUTES.extend(
    [
        ("exact", "/api/command-center/kpi", _get_command_center_kpi),
        ("exact", "/api/command-center/org", _get_command_center_org),
        (
            "exact",
            "/api/command-center/spec-runs",
            _get_command_center_spec_runs,
        ),
        ("exact", "/api/command-center/pipeline", _get_command_center_pipeline),
        ("exact", "/api/command-center/ledger", _get_command_center_ledger),
        ("exact", "/api/command-center/inbox", _get_command_center_inbox),
    ]
)

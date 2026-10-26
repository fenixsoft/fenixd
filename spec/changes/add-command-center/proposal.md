## Why

现有两块大屏（collab-graph、spec-topology）面向的是"系统在运转"的指标叙事，向集团管理层展示时说服力不足：管理层要被说服，需要看到的是"AI 像一支有分工的团队在干活，并交付了可验收的成果"。参照 Trinity（github.com/Abilityai/trinity）的"凭证治理"叙事——组织网格、审批收件箱、执行台账、带日期的数字——为 dashboard 增加一块面向管理层演示的严肃企业风指挥中心页。

## What Changes

- 新增后端聚合数据层 `core/dashboard/data/command_center.py`：跨项目聚合出 KPI 四指标（7 日交付 SPEC 数、人工介入率、7 日 run 成功率、单 SPEC 成本）、组织网格数据（车道卡 + 部门分区 + 汇报线）、交付流水线（SPEC 状态五列看板）、执行台账（近期 run 行）、裁决收件箱装配（复用既有 admin_alerts + adjudication_choices）。
- 新增只读路由 `core/dashboard/routes/command_center_routes.py` 并在 `core/dashboard/server.py` 注册：`GET /api/command-center/{kpi,org,pipeline,ledger,inbox}`，支持可选 `project` 筛选参数（与 collab-graph 同一注入模式）。
- 新增前端页面 `src/pages/command-center/`（指挥中心，路由 `/command-center`），含四屏 Tab 切换：组织总览（部门分区 + 静态汇报线 + 车道卡）、交付流水线（状态泳道）、裁决收件箱（一键决策卡，复用既有 `POST /api/alert-resolve`）、执行台账（KPI 条 + run 行）。顶栏导航加入口。
- 风格约束：严肃企业控制台（暗色、数据墨水优先、静态细线画汇报线），禁止插画/动画小人/吉祥物。
- SPEC 详情钻取复用既有 `/projects/:name/:spec` 页面，不新建详情页。

## Capabilities

### New Capabilities
- `command-center-aggregation`: 指挥中心后端聚合——KPI 四指标的精确派生口径、车道部门分区静态映射与组织网格数据、SPEC 状态流水线派生、执行台账行、裁决收件箱装配（对既有 choices/alert-resolve 事实源只读消费）。
- `command-center-console-ui`: 指挥中心前端四屏 UI——组织总览、交付流水线、裁决收件箱、执行台账，含顶部 KPI 条、导航入口、 drill-down 到既有 SPEC 详情页、一键裁决交互。

### Modified Capabilities

## Impact

- 后端：`core/dashboard/data/`（新增 command_center.py）、`core/dashboard/routes/`（新增 command_center_routes.py）、`core/dashboard/server.py`（注册 mixin）。
- 前端：`core/dashboard/static/` 的 routes.ts、app.tsx（导航）、services/dashboard.ts（API client）、新增 pages/command-center/ 四屏组件。
- 只读消费既有数据源：run metric index（runs.py）、STATE.md 状态（state.py）、admin_alerts、adjudication_choices、项目配置（网关配置态派生，不发探测；llm_health 为按需主动探测工具，不复用）；不新增 POST 端点（裁决走既有 alert-resolve）。
- 无配置项新增（部门分区/汇报线为模块级静态常量，避免配置+UI 连带义务）；无数据迁移；无破坏性变更。

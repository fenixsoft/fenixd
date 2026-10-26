## Context

dashboard 已有两块大屏能力：collab-graph（`core/dashboard/data/collab_graph.py` + `routes/collab_graph_routes.py`，跨项目角色协作图谱）与 spec-topology（`data/topology.py` + `routes/topology_routes.py`，单 SPEC 拓扑）。指挥中心是第三块，叙事对象从「系统运转」换成「AI 团队交付」（参照 Trinity 的组织网格/收件箱/台账/带日期的数字）。既有可复用事实源：run metric index（`data/runs.py`，含 classify_run / compute_run_cost / 在飞判定 / `run_activity`）、STATE.md 状态读取（`data/state.py`）、admin_alerts + adjudication_choices（`data/admin_alerts.py` / `data/adjudication_choices.py`，choices 快照随告警落盘）、裁决执行（既有 `POST /api/alert-resolve`）、网关健康（`core/dashboard/llm_health.py`）。前端为 umi + antd React SPA，路由表 `static/config/routes.ts`，导航 `src/app.tsx` menuDataRender，API client `src/services/dashboard.ts`。

## Goals / Non-Goals

**Goals**
- 管理层 90 秒演示路径可达：组织总览 → SPEC 钻取 → 现场批一张裁决卡 → 台账与 KPI 收尾。
- 全部指标口径单一、可测试（每个 KPI 一个精确派生定义 + fixture Scenario）。
- 只读聚合层 + 零新 POST 端点（裁决复用既有 alert-resolve）。

**Non-Goals**
- 不做实时推送（SSE/WS）——轮询即可满足演示节奏。
- 不做新详情页——复用 `/projects/:name/:spec`。
- 不做用户可配置的分区/汇报线/刷新间隔——全部模块常量。
- 不做跨日历史归档存储——所有窗口指标从既有 run 文件与目录名即时聚合。

## Decisions

**D1 聚合层单文件 `data/command_center.py`，路由单 mixin `routes/command_center_routes.py`**。与 topology/collab-graph 同构（data 模块 + routes mixin + server.py 注册 mixin），跨项目聚合入口签名沿用 `aggregate_*(registry_projects, project=None)` 注入模式。备选：并入现有模块——拒绝，职责与既有模块正交且体量不小。

**D2 部门分区与汇报线为模块级静态常量（ROSTER/EDGES），不做配置项**。理由：演示页的组织叙事是产品决策而非用户偏好；避免「新增配置项必须带 Dashboard 界面」的连带义务；后续若需定制再升配置。未登记 lane 落「其他」分区，花名册外车道不丢。

**D3 KPI 窗口指标全部即时聚合，不建缓存表**。数据量：活跃 run 文件量级为百/日，14 日 sparkline 与 7 日 KPI 在单请求内可算；run metric index 已有 memo 缓存（`_load_run_metric_index`）。备选：预聚合定时任务——拒绝，引入新状态与失败面，收益不匹配量级。

**D4 收件箱只装配不执行**。choices 读告警记录内快照（D2 语义），执行走既有 `POST /api/alert-resolve` + 既有 destructive 二次确认语义；指挥中心前端不复制裁决动词映射。

**D5 前端四屏一页 + Tab 切换，单页轮询（常量 60s）**。备选：四条独立路由——拒绝，演示时需一屏内切换；Tab 保持各自数据独立加载与独立错误降级。

**D6 风格约束落为可测试场景**：「无动画/插画」写成 Scenario（渲染产物无 animation 角色元素、汇报线为静态 SVG），验收时人工 + 代码双侧核对。

## Risks / Trade-offs

- [run 文件量大时 14 日聚合变慢] → 复用 run metric index memo 缓存；聚合按文件 mtime 粗筛入窗文件，窗口外文件不读内容。
- [STATE.md pushed 条目无终态时间戳，delivered_7d 口径混入「历史 pushed」] → 口径明示为「窗内归档 + 当前 pushed」，Scenario 固化；不做时间戳猜测。
- [trigger 字段既有数据缺口] → 口径允许 null，台账列显示「—」，不硬造默认值。
- [车道与告警的映射脆弱] → 组织卡状态只用「有无在飞 run」二元判定，不做 lane↔告警信号映射；待裁决状态仅出现在收件箱屏。
- [新页面与暗色主题不一致] → 复用既有 antd 暗色 token 与 tailwind 配置，不引入新色板。

## Migration Plan

纯增量：新 data 模块 + 新路由 mixin + server.py 一行注册 + 前端新页面与导航项。无状态迁移、无配置变更、无破坏性接口。回滚 = 还原注册行与前端入口。前端产物 `static/dist/` 按惯例不入库（构建重建，声明为 reference）。

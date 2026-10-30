# Proposal: add-collab-graph-bigscreen

## Why

SPEC 协作拓扑大屏（`add-spec-topology-bigscreen`）解决单 SPEC 的协作叙事；管理层还需要更高一层的「AI-Native 组织画像」：整个工程范围内所有 Agent 的协作全景——哪些角色承担了多少工作、角色间交接多频繁、当前在飞什么。该视角在 dashboard 的跨项目枢纽页（overview）进入，以 IOC 大屏形态呈现。

## What Changes

- 后端新增跨项目聚合端点 `GET /api/overview/collab-graph`：对所有项目全部 SPEC 复用 `derive_topology` 派生结果，聚合出**角色级协作图谱**（角色为节点、跨角色交接为边、次数为边权、成本/时长为节点权重）与全局 KPI
- 前端新增「脱壳」全屏深色大屏页面（路由 `/overview/collab-graph`）：手写 SVG 角色协作图谱，角色按 SDLC 阶段固定就位（无力导向），在飞脉动、边随数据实时变化
- overview 页新增大屏入口
- 项目维度：主图默认聚合全部项目，提供项目筛选器切换聚合范围；点角色节点/边下钻明细面板（最近交接/run 列表，含项目与 SPEC 归属），可跳转对应 SPEC 的单 SPEC 协作拓扑大屏
- 已归档 SPEC 计入 KPI 计数，但不产出图谱边（run 产物已随归档清理），图谱口径有显式注记

## Capabilities

### New Capabilities

- `collab-graph-aggregation` — 跨项目角色级图谱聚合端点：复用 topology 派生、角色归并与 attempt 归并逻辑，零第二套映射
- `collab-graph-bigscreen-ui` — 协作图谱大屏前端：overview 入口、固定就位图谱、筛选器、下钻面板、跨大屏跳转

### Modified Capabilities

（无——消费 `add-spec-topology-bigscreen` 的 `topology-derivation` 产物但不修改其行为；本 SPEC 经 `depends_on` 排在其后执行）

## Impact

- **影响代码**：`core/dashboard/data/`、`core/dashboard/routes/`、`core/dashboard/server.py`、`core/dashboard/static/src/pages/overview/`、`core/dashboard/static/src/services/dashboard.ts`、`core/dashboard/static/config/routes.ts`
- **零改动红线**：overview 现有内容仅新增入口；单 SPEC 大屏、SpecTimeline、归档链路零改动
- **依赖**：`depends_on: add-spec-topology-bigscreen`（复用其 `topology.py` 派生引擎与 `runVisual.ts` 常量）
- **无新增配置项**、无数据迁移、无破坏性变更

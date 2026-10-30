# Design: add-collab-graph-bigscreen

## Context

单 SPEC 协作拓扑大屏（`add-spec-topology-bigscreen`，depends_on 前序）提供微观协作叙事；本 change 补上宏观「AI-Native 组织画像」：跨项目聚合所有 Agent 协作全景，从 overview 枢纽页进入。用户选型（AskUserQuestion 定稿）：**角色协作图谱**形态（角色为节点、交接为边、次数为边权、成本为权重）+ **跨项目总览**范围 + full + 立即排队。

## Goals / Non-Goals

- Goals：跨项目角色级协作图谱大屏（固定就位、无图布局算法）、项目筛选、下钻明细与跨大屏跳转、实时刷新、零新依赖
- Non-Goals：力导向布局（上一轮已否，本项目继续沿用确定性布局）、单 SPEC 级管线在总览重绘（那是单 SPEC 大屏职责）、归档数据恢复、图编辑

## Decisions

1. **聚合复用而非复写**：`core/dashboard/data/collab_graph.py` 逐 SPEC 调用前序 SPEC 的 `derive_topology` 在其结果上聚合；角色归列/attempt 归并零第二套实现。依赖经 `depends_on: add-spec-topology-bigscreen` 串行化，规避同文件并行冲突。
2. **固定就位布局**：8 角色按 SDLC 流向固定坐标（确定性布局），两次进入位置一致——管理层跨日汇报可比对；边宽/节点大小/脉动承载数据变化。
3. **「聚类/分组」的落法**：用户同时选了跨项目总览与聚合图谱预览（单图全聚合）。落法为主图全局聚合 + 项目筛选器切换范围（全部/单项目）——不按项目复制 N 份角色图（那会稀释「一个组织一张图」的叙事，也徒增布局复杂度）。
4. **下钻两级**：角色节点/边 → 明细面板（最近 run/交接列表，含项目与 SPEC 归属）→ 跳转对应 SPEC 的单 SPEC 大屏。归档 SPEC 条目标注不可跳转（由单 SPEC 大屏降级提示兜底）。
5. **归档口径**（延续前序用户选型 a）：归档 SPEC 计 KPI 不进图（run 产物已清理），响应携 `archived_excluded` 计数，前端显式注记；聚合不读归档产物（天然零开销）。
6. **技术栈延续**：手写 SVG + React 零图表库；复用 `runVisual.ts` 常量（状态色/角色名）；端点挂 `core/dashboard/routes/collab_graph_routes.py`（server.py Mixin 接入），`/api/overview/collab-graph` 对齐既有 overview 命名空间。
7. **实时刷新**：SSE 失效重拉全量聚合（角色级聚合数据量小，全量渲染成本可接受）+ 30s 轮询兜底，与前序 SPEC 同策略。

## Risks / Trade-offs

- **聚合端点扫描面**：全项目全 SPEC 逐个 derive，项目/SPEC 数量大时延迟上升——归档 SPEC 零产物读取使大头天然消失，活跃 SPEC 量级小；若实测仍慢，缓存/增量留实现裁量（spec 只约束只读与口径，不约束实现策略）。
- **角色图谱信息密度 vs 单 SPEC 细节**：宏观图不含时间轴，时间维度故事由单 SPEC 大屏承担，两级下钻打通互补。
- **依赖单点**：本 SPEC 全部价值建立在前序 `topology.py` 之上，前序返工会联动本 SPEC——depends_on 串行已把风险排序为「先后」而非「并行冲突」。

## Open Questions

（无——形态、范围、模式、时机均已由用户定稿）

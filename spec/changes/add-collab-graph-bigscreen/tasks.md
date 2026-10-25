## Deliverables

```yaml
- path: core/dashboard/data/collab_graph.py
  kind: new
- path: core/dashboard/routes/collab_graph_routes.py
  kind: new
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/config/routes.ts
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/overview/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/overview/collabGraph/index.tsx
  kind: new
- path: core/dashboard/static/src/pages/overview/collabGraph/CollabGraphView.tsx
  kind: new
- path: tests/test_collab_graph_aggregation.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 后端图谱聚合引擎

- [ ] 1.1 新建 `core/dashboard/data/collab_graph.py`：`aggregate_collab_graph(project=None)` 遍历托管项目全部 SPEC，逐个调用 `derive_topology` 并在其结果上聚合角色级图谱（8 角色固定集、跨角色交接边含 weight、节点累计成本/时长/run 计数/在飞计数、全局 KPI）；角色归列与 attempt 归并零第二套实现（纯复用 topology.py）
- [ ] 1.2 归档口径：已归档 SPEC 计入 kpis SPEC 计数、响应携 `archived_excluded` 计数，不产出边与权重；聚合对其跳过 run 产物读取（零文件读取），不触发任何归档产物访问
- [ ] 1.3 边界鲁棒：空项目（零 SPEC）与全归档项目聚合不抛错、零读取；`project` 参数收窄聚合范围

## 2. 后端端点与单测

- [ ] 2.1 新建 `core/dashboard/routes/collab_graph_routes.py`：只读端点 `GET /api/overview/collab-graph`（支持 `project` 可选参数，复用现有鉴权约定），`core/dashboard/server.py` 以 Mixin 方式接入
- [ ] 2.2 新建 `tests/test_collab_graph_aggregation.py`：表驱动覆盖任务 1.1–1.3 全部 Scenario（多项目聚合边权重求和、项目筛选收窄、跨项目在飞计数、归档只进 KPI、空项目不抛错）

## 3. 前端大屏页面

- [ ] 3.1 `core/dashboard/static/config/routes.ts` 新增 `/overview/collab-graph` 路由；`core/dashboard/static/src/services/dashboard.ts` 新增 `getCollabGraph` 与图谱类型定义
- [ ] 3.2 新建 `core/dashboard/static/src/pages/overview/collabGraph/index.tsx`：脱壳全屏深色壳（无框架侧边栏）、标题 + 全局 KPI 条 + 项目筛选器（全部/各项目，选中态可辨）+ 退出返回 overview、SSE 失效全量重拉（30s 轮询兜底）、归档口径注记（`archived_excluded > 0` 时可见）
- [ ] 3.3 新建 `core/dashboard/static/src/pages/overview/collabGraph/CollabGraphView.tsx`：手写 SVG 角色固定就位图谱（8 角色 SDLC 流向确定性坐标，两次进入位置一致）、节点大小映射成本或时长、在飞角色发光脉冲（消费 runVisual 常量）、边宽映射交接 weight 且带方向指示、点击节点/边打开下钻明细面板（最近 run/交接列表含项目名/SPEC 名/时间/状态，可跳转 `/projects/<name>/<spec>/topology`，归档条目标注不可跳）
- [ ] 3.4 `core/dashboard/static/src/pages/overview/index.tsx` 新增「协作图谱大屏」入口（仅新增，不动既有内容渲染逻辑）

## 4. 构建与验收

- [ ] 4.1 前端构建更新产物（`core/dashboard/static/dist/index.html` 锚点刷新），前后端 lint 与测试全绿
- [ ] 4.2 以 fixture 项目端到端自验并记录：多项目聚合图谱渲染与固定就位、筛选切换、下钻面板与跨大屏跳转、归档注记与 KPI 口径；零改动红线 diff 自检（overview 仅入口新增、单 SPEC 大屏与归档链路无 diff）

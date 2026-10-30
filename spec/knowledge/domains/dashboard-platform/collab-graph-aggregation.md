# 跨项目协作图谱聚合端点

<!-- knowledge: capability=collab-graph-aggregation rev=1
     sources=spec/archive/2026-10-30-add-collab-graph-bigscreen -->

「AI-Native 组织画像」的数据面：对 dashboard 托管全部项目的全部 SPEC 聚合出角色级协作图谱（角色为节点、跨角色交接为边），宏观呈现哪些角色承担多少工作、交接多频繁、当前在飞什么。

## 规则

- **聚合端点**：`GET /api/overview/collab-graph` 返回 `roles`（固定角色集节点：用户/fenix-new、PMEngine、需求评审、规划、开发、审查/修复、测试/验证、运维，恒 8 个）、`edges`（跨角色交接边，`weight`=交接次数）、`kpis`（SPEC 总数/在飞数/总成本/总 run 数/总交接次数）。端点只读、无副作用，不写任何运行时状态。
- **口径单源复用**：角色粒度与单 SPEC 拓扑泳道同源——复用 `core/dashboard/data/topology.py` 的 `_ROLE_TABLE` 归列、attempt 归并逻辑与用户/PMEngine 特殊节点，MUST NOT 复制第二套前缀映射。
- **范围收窄**：可选 `project` 查询参数将聚合收窄到单项目（其余项目不入图）；无参数时全局聚合。
- **下钻明细内嵌**：响应内嵌下钻明细——每个角色节点与每条边各附最近交接/run 明细列表（`recent_runs`，每条含项目名、SPEC 名、时间、状态），前端下钻面板直接渲染，MUST NOT 要求前端为下钻再逐项目调用其他端点。
- **节点权重与在飞语义**：角色节点携带聚合指标——累计成本（Σ run cost_usd）、累计 run 时长、run 计数、在飞计数；在飞 = 任一项目该角色存在 running run（跨项目计数累加）。
- **归档口径**：已归档 SPEC（run 产物已清理）计入 `kpis` 的 SPEC 计数，但 MUST NOT 产出图谱边或节点权重；响应携带口径说明字段（`archived_excluded: <N>`）供前端显示注记；MUST NOT 为聚合而读取或恢复归档产物（归档 SPEC 零读取开销）。
- **聚合实现边界**：聚合计算逐 SPEC 调用 `derive_topology` 并在其结果上聚合（单 SPEC 粒度缓存留实现裁量）；从未跑过任何 SPEC 的空项目贡献零边零权重、正常返回不抛错。

## 溯源

- 2026-10-30 add-collab-graph-bigscreen（spec/archive/2026-10-30-add-collab-graph-bigscreen） — 新增本能力：跨项目角色级聚合端点（复用 derive_topology 零第二套映射）、project 筛选参数、下钻明细内嵌、节点权重与跨项目在飞聚合、归档 SPEC 计 KPI 不进图口径

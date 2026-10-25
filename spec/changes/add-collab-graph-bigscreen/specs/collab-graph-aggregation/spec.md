## ADDED Requirements

### Requirement: 跨项目角色图谱聚合端点

后端 MUST 提供只读端点 `GET /api/overview/collab-graph`，对 dashboard 托管全部项目的全部 SPEC 聚合出角色级协作图谱：`roles`（固定角色集节点：用户/fenix-new、PMEngine、需求评审、规划、开发、审查/修复、测试/验证、运维）、`edges`（跨角色交接边，含 `weight`=交接次数）、`kpis`（SPEC 总数/在飞数/总成本/总 run 数/总交接次数）。角色粒度 MUST 与单 SPEC 拓扑的七阶段列角色映射同源（复用 `core/dashboard/data/topology.py` 的归列与 attempt 归并逻辑），MUST NOT 复制第二套前缀映射。端点 MUST 支持可选 `project` 查询参数将聚合范围收窄到单项目。

#### Scenario: 全局聚合出角色图

- **WHEN** 两个项目分别有经历「规划→开发→审查」交接的 SPEC 并调用端点（无 project 参数）
- THEN「规划→开发」「开发→审查」边的 weight 为两项目相应交接次数之和，角色节点固定为 8 个

#### Scenario: 项目筛选收窄

- **WHEN** 携带 `project=<name>` 调用端点
- **THEN** 聚合仅含该项目 SPEC 的交接与成本，其余项目不入图

### Requirement: 节点权重与在飞语义

角色节点 MUST 携带聚合指标：累计成本（Σ run cost_usd）、累计 run 时长、run 计数、在飞（running）计数。端点数据 MUST 含每个角色的在飞状态（任一项目该角色存在 running run 即在飞），供前端脉动渲染。

#### Scenario: 跨项目在飞聚合

- **WHEN** 项目 A 的开发角色 1 个 run 在飞、项目 B 的开发角色 2 个 run 在飞
- **THEN** 开发节点 running 计数为 3 且标记在飞

### Requirement: 归档 SPEC 口径

已归档 SPEC（run 产物已清理）MUST 计入 `kpis` 的 SPEC 计数，但 MUST NOT 产出图谱边或节点权重（无 run 数据可聚合）；端点响应 MUST 携带口径说明字段（如 `archived_excluded: <N>`），前端据此显示注记。MUST NOT 为聚合而读取或恢复归档产物。

#### Scenario: 归档 SPEC 只进 KPI 不进图

- **WHEN** 项目含 5 个已归档 SPEC（run 产物已删）与 3 个活跃 SPEC
- **THEN** kpis SPEC 计数为 8、`archived_excluded` 为 5，图谱边与权重仅来自 3 个活跃 SPEC

### Requirement: 聚合复用与性能边界

聚合计算 MUST 逐 SPEC 调用 `derive_topology` 并在其结果上聚合（单 SPEC 粒度缓存可留实现裁量）；已归档 SPEC MUST 直接跳过 run 产物读取（产物不存在，零读取开销）。端点 MUST 与现有 dashboard 路由同样只读、无副作用，不写任何运行时状态。

#### Scenario: 归档项目零开销跳过

- **WHEN** 某项目全部 SPEC 均已归档
- **THEN** 聚合不触发任何 run 产物文件读取，仅计入 KPI

#### Scenario: 空项目不报错

- **WHEN** dashboard 存在从未跑过任何 SPEC 的新项目
- **THEN** 聚合正常返回（该项目贡献零边零权重），不抛错

# command-center-aggregation Spec（delta：arbiter 归并质量裁决）

## MODIFIED Requirements

### Requirement: 组织网格数据派生

指挥中心聚合层 SHALL 提供组织网格数据（`GET /api/command-center/org`）：车道卡按部门分区（zone）归组，分区与车道花名册为模块级静态常量（MUST NOT 做成用户配置项）；运行中观测到花名册外的 lane 时 SHALL 归入「其他」分区。观测 lane → 编制内 lane 的归并表 `LANE_ALIASES` SHALL 含 `arbiter → judge`（与既有 `dispute-judge → judge`、`repair → code-fix` 同族）：arbiter 的窗内 run 计数、成功率、成本、时长、在飞归属与 14 日活动并入 judge 卡（质量线「质量裁决」），MUST NOT 在「其他」分区单独出卡。时间线/拓扑屏保持原生 agent_type 的既有定稿口径不变（归并仅组织网格聚合与 spec 视图轮次消费）。

#### Scenario: arbiter 并入 judge 卡

- **WHEN** 观测窗内存在 `arbiter-` 前缀 run（如 arbiter-evo-refine-midflight-outlier-dims-1793464069）
- **THEN** `/api/command-center/org` 响应中 judge 卡 `runs` 计入这些 run，质量线分区 judge 卡统一显示「质量裁决」；响应 zones 中不出现 lane=arbiter 的卡片、「其他」分区无 arbiter 卡

#### Scenario: arbiter 在飞归属并入 judge 卡

- **WHEN** 某 arbiter run 在飞（status ∈ 在飞判定口径）且有可归属 spec
- **THEN** judge 卡 `status=working`，`attributables` 含该 run 的 {project, spec, run_id}，arbiter 无独立卡片

#### Scenario: spec 视图轮次同口径归并

- **WHEN** `GET /api/command-center/spec-runs` 查询某 SPEC 的轮次，且该 SPEC 存在 arbiter run
- **THEN** 该 run 以归并后车道（judge）出列，不出现名为 arbiter 的 lane 条目

#### Scenario: 时间轴与拓扑不受归并影响

- **WHEN** SPEC 运行时间轴 / 拓扑屏读取 arbiter run
- **THEN** 两侧保持原生 agent_type=arbiter（各有角色映射单源），归并表不扩散到这两个消费面

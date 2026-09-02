# fast-track-mode-selection — 模式选择能力

## ADDED Requirements

### Requirement: fenix-new 复杂度评估与明确建议

用户在 fenix-new 创建 SPEC 未指定执行模式时，需求 Agent MUST 评估需求复杂度并给出**明确**的模式建议（建议走 fast-track 或建议走 full），附简要理由，供用户选择。禁止在无建议的情况下默认任一路径。

#### Scenario: 简单需求给出 fast-track 建议
- **WHEN** 用户描述的需求经评估为简单需求（如单点小改动、影响面小、场景少）
- **THEN** 需求 Agent 明确建议「建议走简单模式（fast-track）」并说明理由，同时告知用户可选择完整模式

#### Scenario: 复杂需求给出 full 建议
- **WHEN** 用户描述的需求经评估为复杂需求（如跨模块、含 UI/迁移、验证场景多）
- **THEN** 需求 Agent 明确建议「建议走完整模式（full）」并说明理由，同时告知用户可选择简单模式

### Requirement: 用户显式指定优先

用户显式指定执行模式（fast-track 或 full）时，框架 MUST 尊重用户指定，需求 Agent 不得以评估结果覆盖用户的显式选择。

#### Scenario: 用户覆盖建议
- **WHEN** 需求 Agent 建议 fast-track 但用户明确要求走 full
- **THEN** 该 spec 以 `mode=full` 创建，Agent 不再追问或改写

### Requirement: 模式元数据写入与缺省值

确认后的执行模式 MUST 写入 spec 元数据，daemon 派发时据此选择路径；未写入 mode 字段的存量 spec MUST 按缺省 `full` 处理。

#### Scenario: fast-track 元数据落盘
- **WHEN** 用户确认走 fast-track 后 SPEC 创建完成
- **THEN** spec 元数据含 `mode: fast-track`，daemon 拾取该 spec 时读取并选择快速路径派发

#### Scenario: 存量 spec 缺省 full
- **WHEN** spec 元数据中不存在 mode 字段
- **THEN** daemon 按完整模式流水线处理，行为与引入本能力之前完全一致

### Requirement: Dashboard 模式标记

Dashboard 的 spec 列表与详情页 SHALL 展示每个 spec 的执行模式标记（fast-track / full），存量无 mode 字段的 spec 按缺省 full 展示或显示为 full 等价标记。

#### Scenario: 列表展示模式标记
- **WHEN** Dashboard spec 列表渲染含 fast-track spec 的项目
- **THEN** fast-track spec 行展示可辨识的模式标记，与 full spec 区分

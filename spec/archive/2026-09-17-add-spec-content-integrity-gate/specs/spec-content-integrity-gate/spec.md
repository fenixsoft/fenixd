# spec-content-integrity-gate 增量规格

## ADDED Requirements

### Requirement: 派发前内容完整性校验
派发 implementer 或 fast-track 之前，系统 MUST 校验 `spec/changes/<spec_name>/` 目录是否含实质内容。目录不存在、目录为空、或其中不存在 `proposal.md` / `design.md` / `tasks.md` / `specs/**/*.md` 任一文件时，判定为空 spec，MUST 中止派发。

#### Scenario: 空目录中止派发
- **WHEN** spec 状态为 ready 且 `spec/changes/<spec_name>/` 目录为空
- **THEN** 不启动 implementer run，状态置 blocked，告警注明 spec 内容缺失

#### Scenario: 只有无关文件
- **WHEN** spec 目录内只有非 spec 内容文件（如 `.DS_Store`、日志），无 proposal/design/tasks/specs
- **THEN** 判定为空 spec，中止派发并置 blocked

#### Scenario: 含实质内容正常派发
- **WHEN** spec 目录内存在 `tasks.md`（或 proposal/design/specs 之一）
- **THEN** 校验通过，按既有逻辑派发

#### Scenario: 读目录异常保守放行
- **WHEN** 校验读取目录时抛出 IO 异常（权限、临时不可达等）
- **THEN** 记 WARNING 并放行派发，不因此误伤正常 spec

### Requirement: 空 spec 冻结处置
命中内容完整性闸门时，系统 MUST 复用预算闸门的冻结范式：状态写入 `blocked`，`error` 字段记录「SPEC 内容缺失」原因，并通过 `_send_human_escalation_alert` 发一条 `signal_type=spec_content_missing`、`severity=major` 的人工裁决告警。处置 MUST 幂等——已是 blocked 的 spec 不重复发告警但仍拒绝重派。

#### Scenario: 闸门命中冻结
- **WHEN** 派发前校验判定空 spec
- **THEN** 状态置 blocked、回滚队列占用、发 `spec_content_missing` 告警，且不回落下一次派发

#### Scenario: 已冻结幂等
- **WHEN** 空 spec 已是 blocked，派发逻辑再次评估
- **THEN** 不重复发告警，拒绝重派

### Requirement: 告警生命周期闭环
`spec_content_missing` 告警 MUST 接入 `alert_lifecycle._SIGNAL_CONDITIONS`，映射到 `spec_terminal_or_unblocked` 条件：spec 补上内容、解冻并离开 blocked（或到达终态）后，该告警自动标记 resolve，无需人工清理。

#### Scenario: 补内容后自动闭环
- **WHEN** 空 spec 的告警已产生，人工补上 spec 内容并解冻使状态离开 blocked
- **THEN** 该告警被 `auto-resolve` 标注闭环

#### Scenario: 未接闭环不得自动消失
- **WHEN** 空 spec 保持 blocked
- **THEN** 告警保持未 handled，等待人工处置
## ADDED Requirements

### Requirement: 验证完成度放行闸门

SPEC 在验证流程已启动（存在该 SPEC 的 verifier 运行记录或 `.fenix/verify-progress/<spec>.json` 进度文件）的情况下，状态推进到 `done` 或 `pushed` 之前，框架 MUST 校验该 SPEC 的验证进度 `done == total`（进度文件缺失或无法解析视同未完成）；未全量完成时 MUST 阻止推进，保留在验证相关状态（如 `verified`/`testing`），并在该 SPEC 的状态记录中写入未完成原因（含 `done`/`total` 数值与最近一次 `current` 场景描述）。验证流程尚未启动（无 run 记录、无进度文件）的 SPEC 不受此限，维持原推进路径。

#### Scenario: 验证未全量完成被阻止放行

- **WHEN** `improve-dashboard-sections` 的验证进度为 `{"total": 34, "done": 0, "current": "初始化..."}`，框架将其状态从验证中推进到 `done`
- **THEN** 推进被阻止，spec 仍处于 `testing`/`verified` 等验证状态，状态记录包含「验证未完成：0/34」及原因；不得进入 `done`，更不得 `pushed`

#### Scenario: 验证全量完成正常放行

- **WHEN** 某 SPEC 的验证进度为 `{"total": 32, "done": 32}`（全部场景完成）
- **THEN** 状态正常推进到 `done`/`pushed`，不受闸门阻碍

#### Scenario: 无验证流程的 SPEC 不受影响

- **WHEN** 某 SPEC 从未触发验证（无 verifier run 记录且无进度文件）
- **THEN** 其状态推进保持原行为，闸门不介入

### Requirement: 耗时列真实性验证断言

verifier 验证 SPEC 表格「耗时」列时 MUST 区分两种「—」：无任何运行记录的 SPEC 显示「—」为合法占位；有运行记录的 SPEC 耗时列显示「—」或 0 MUST 判定为缺陷并报告（运行记录存在但 `duration_seconds` 聚合为 0 说明时长计算异常）。验证报告 MUST 记录被检查的 SPEC 及其 run 数量、判定依据。

#### Scenario: 有运行记录但耗时为空判定缺陷

- **WHEN** verifier 检查某 SPEC（`.fenix/runs/` 下存在其多条 run 文件）的「耗时」列，显示为「—」
- **THEN** 该场景判定为失败，报告写明该 SPEC 有 N 条运行记录而总耗时异常为 0，触发缺陷上报而非视为合法占位

#### Scenario: 无运行记录显示占位合法通过

- **WHEN** 某草稿 SPEC 无任何运行记录，「耗时」列显示「—」
- **THEN** 该场景判定通过，符合 `spec-table-improvements` 的占位语义
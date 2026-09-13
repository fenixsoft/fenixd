# frozen-scenario-schema-migration 增量规格

## ADDED Requirements

### Requirement: 冻结场景读侧旧 schema 兼容迁移
加载冻结场景文件时，系统 MUST 识别旧 schema 字段形态：run 步骤的 `value` 字段迁移为 `command`，output_match 断言的 `value` 字段迁移为 `expected`；迁移后走既有校验。迁移 MUST 仅对『目标字段缺失且旧字段存在』生效（新 schema 字段存在时零干扰），迁移失败的条目 MUST 在报错中列出具体字段差异（场景 id / 下标 / 缺失字段清单），不得以笼统『corrupt』吞掉诊断信息。

#### Scenario: 旧 schema 文件自动迁移通过验收
- **WHEN** 冻结文件 run 步骤含 `value` 而非 `command`、output_match 断言含 `value` 而非 `expected`
- **THEN** 读侧自动迁移后校验通过，场景正常冻结执行，不判 corrupt

#### Scenario: 新 schema 文件行为零变化
- **WHEN** 冻结文件已含 `command` / `expected` 字段
- **THEN** 不做迁移，校验路径与现状一致

#### Scenario: 真损坏报字段级差异
- **WHEN** 文件既无新字段也无旧字段（字段整体缺失）
- **THEN** 判 corrupt，但报错列出具体字段差异清单（场景 id/下标/缺失项）供 admin 精准修复

### Requirement: 场景文件 schema 版本标记
场景写入端 MUST 在持久化文件中写入 `schema_version` 结构化标记；读侧按版本路由迁移（当前版本直通、旧版本迁移、未知版本保守按迁移尝试+差异报错）。

#### Scenario: 版本标记写入
- **WHEN** 写端持久化/补齐/冻结任意场景集
- **THEN** 文件含 schema_version 字段（具体值按 design 固化）

### Requirement: blocked_stuck 处置后自动复位
admin 处置成功（disposition result=resolved）且处置内容修好根因后，若 spec 仍处于 blocked 且阻塞类型为 blocked_stuck，MUST 自动复位 spec 状态（复用 env 阻塞族的复位范式：实现分支已合并则直通重验，否则回 ready），MUST NOT 等待人工二次介入。

#### Scenario: 处置修复后自动复位
- **WHEN** admin 处置成功修复根因（如场景文件）且 spec 阻塞类型为 blocked_stuck
- **THEN** 自动按既有复位路径恢复并触发重验，blocked_stuck 不再二次空转 15+ 分钟

#### Scenario: 处置未完成不动状态
- **WHEN** admin 处置 run 无 result=resolved
- **THEN** 不自动复位，保持既有阻塞
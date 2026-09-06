# verify-scenario-freeze 增量规格

## ADDED Requirements

### Requirement: 场景集持久化
首轮验证裁决产出场景集时，系统 MUST 将 scenario_id 列表（含 description）持久化到 `.fenix/verify-progress/<spec>/scenarios.json`；已有该文件时 MUST NOT 无条件覆盖。

#### Scenario: 首轮写入
- **WHEN** 某 spec 完成首轮验证（11 场景）
- **THEN** scenarios.json 记录 11 个 scenario_id 与描述及轮次来源

### Requirement: 修复轮复用持久化集
spec 处于修复轮（存在 `_verify_fail_rounds` 或 tasks.md 含「验证修复」段）时，验证场景 planner MUST 以持久化集为基准生成场景；新增场景仅允许覆盖修复段声明的新增交付范围。

#### Scenario: 修复轮不扩容
- **GIVEN** 持久化集 11 场景，修复段仅声明修复既有 bug
- **WHEN** 修复轮验证 planner 运行
- **THEN** 产出场景集与持久化集一致（scenario_id 集合相同），不得新增

#### Scenario: 新增范围允许追加
- **GIVEN** 修复段声明新增「导入导出」交付
- **WHEN** 修复轮验证 planner 运行
- **THEN** 场景集 = 持久化集 + 仅针对导入导出的新场景
- **AND** 合并结果写回 scenarios.json（记录追加轮次）

### Requirement: 删减须有理由并留痕
planner 产出缺少持久化集中既有场景时，系统 MUST 要求理由（如对应用例代码已删除），并在验证报告中列出「本轮移除的场景及理由」；无理由的缺场景按 planner 输出不完整处理。

#### Scenario: 有理由的删减被记录
- **WHEN** planner 移除 1 个场景且附理由「对应功能已按任务书移除」
- **THEN** 验证报告含「移除场景」小节列出该场景与理由
- **AND** scenarios.json 同步移除并记录轮次

#### Scenario: 无理由缺场景被拦截
- **WHEN** planner 产出缺少持久化场景且无理由
- **THEN** 场景集校验失败，本轮验证以持久化集补齐缺失场景后继续（不中断验证）

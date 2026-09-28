# codefix-test-targets-sanitization 能力规格（delta）

## ADDED Requirements

### Requirement: 回退路径占位符消毒

code-fix 批回归 spec 回退全量执行时（链末批恒全量、触碰面映射空集、定向配置关、定向重试轮 mapped=False），若命令含 {test_targets} 占位符，框架 SHALL 消毒该命令（str 与 list 两态把占位符替换为缺省 tests/）后再执行；不含占位符的命令 SHALL 保持逐字不变。

#### Scenario: 占位符在回退中被替换

- **WHEN** spec cmd 含 {test_targets}（str 或 list 形态）且任一回退场景触发
- **THEN** 实际执行的命令中占位符已被替换为 tests/
- **AND** 回归正常执行，不出现字面占位符导致的收集失败

#### Scenario: 无占位符零迁移

- **WHEN** spec cmd 不含占位符
- **THEN** 回退行为与改动前逐字一致

### Requirement: 定向路径行为不变

定向分支的占位符替换与环境变量双轨行为 SHALL 保持现状；用于定向判别的 spec SHALL NOT 被预替换。

#### Scenario: 定向场景逐字回归

- **WHEN** 既有定向场景（替换、双轨、触碰面映射）触发
- **THEN** 行为与既有测试断言一致，全绿
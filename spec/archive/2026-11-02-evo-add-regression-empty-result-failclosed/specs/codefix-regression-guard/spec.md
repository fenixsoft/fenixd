# 能力规格：codefix-regression-guard

## ADDED Requirements

### Requirement: 空结果 fail-closed

定向回归判定 MUST NOT 在「命令未真实跑出用例」时给出 passed。

#### Scenario: 非零退出且零用例不得判 passed

- **When** 定向回归命令退出码非 0 且解析所得 JUnit XML 用例总数为 0（含 pytest usage error（exit=4）与零收集（exit=5）形态）
- **Then** 系统按 parse_error/infra 失败链路处置（含既有留痕与批次收尾语义），MUST NOT 判 passed

### Requirement: 结果新鲜度

#### Scenario: 陈旧 XML 不得采信

- **When** 拟据 JUnit XML 判 passed 且该文件 mtime 早于本次命令 started_at
- **Then** 系统按空结果 fail-closed 同类失败处置，MUST NOT 采信陈旧结果

### Requirement: 定向 targets 消毒

#### Scenario: 毒化目标被过滤且双通道同源

- **When** 构造定向回归目标列表（触碰面映射产物）时混入 # 前缀项、__pycache__ 路径/.pyc 文件或不存在路径
- **Then** 系统 SHALL 在单点 producer 处过滤这些项，使执行命令 {test_targets} 替换与 FENIX_TEST_TARGETS 环境变量导出两条注入通道同享消毒后列表（仅在任一消费点过滤均视为未满足），并 SHALL 对被过滤项留 WARNING 痕（含过滤原因）；消毒后为空集时沿用既有 fail-open 回退全量语义

### Requirement: 哨兵残留消除

#### Scenario: 哨兵 # 不残留进执行命令

- **When** 替换声明中的 {test_targets} 占位时
- **Then** 系统 SHALL 保证哨兵符号 # 不残留进最终执行命令（替换时吞掉紧邻 # 或在替换值层规范化）；.fenix/verify.yaml 声明本身不改

## 行为约束

- targets 合法且命令真实执行产出新鲜非空（total>0）结果时，判定行为、批次吞吐、salvage 语义均不变；空结果（total=0）形态按 R1 收口（含 targets 合法但零收集的 rc=5 形态，伪绿转失败是明示取舍）。
- fail-closed 触发时按既有 parse_error/infra 失败链路处置（含留痕与批次收尾语义），不新增告警通道；「XML 新鲜且 total>0 的收尾崩溃」既有豁免（core/regression.py:1037-1047）保留不动。

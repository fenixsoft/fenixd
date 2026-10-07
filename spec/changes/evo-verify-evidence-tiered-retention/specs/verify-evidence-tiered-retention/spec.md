# Spec Delta: verify-evidence-tiered-retention

能力：验证证据按体积/类型分级留存——契约声明阈值，超阈值二进制以哈希与登记信息替代入库。

## ADDED Requirements

### Requirement: 契约分级字段 evidence_retention.max_binary_bytes

verify 契约模板（core/verify_contract_template.yaml）SHALL 新增可选分级声明字段 evidence_retention.max_binary_bytes，契约解析（core/verify_contract.py 的 load_verify_contract 与 validate_contract）SHALL 按以下语义消费：

- 缺省 10485760（10MB）；
- 缺失或非法值时静默回退缺省，不报错、不阻断契约加载（仿 _positive_int_or_default 回退范式）；
- 解析结果 SHALL 暴露给落位指引渲染消费。

#### Acceptance Scenario 1: 声明值生效
- WHEN 契约声明 evidence_retention.max_binary_bytes 为合法正整数
- THEN 解析结果取声明值

#### Acceptance Scenario 2: 非法值回退缺省
- WHEN 契约声明的 max_binary_bytes 为非法值（负数、非整数或 bool）
- THEN 解析静默回退缺省 10485760，契约加载不报错

#### Acceptance Scenario 3: 缺失走缺省
- WHEN 契约未声明 evidence_retention
- THEN 解析结果为缺省 10485760

### Requirement: 落位指引分级条款

证据落位指引文本（prompt 注入段，core/agent_runner/prompt_builder.py 的证据落位节）SHALL 包含分级留存规则：

- 文本/JSON/哈希/小日志直接入库；
- 超过契约阈值的二进制证据 SHALL NOT 入 git，改落 sha256 sidecar、复现命令与存放路径登记文件；
- 阈值 SHALL 随契约声明联动（未声明时为缺省 10MB）。

#### Acceptance Scenario 4: 契约声明阈值形态渲染分级条款
- WHEN 契约声明了自定义阈值且落位指引渲染
- THEN 指引文本包含分级条款，且阈值取契约声明值

#### Acceptance Scenario 5: 缺省阈值形态渲染分级条款
- WHEN 契约未声明阈值（走缺省 10MB）且落位指引渲染
- THEN 指引文本同样包含分级条款

# verify-contract-serve-sync Specification

## ADDED Requirements

### Requirement: 出题产物落盘时按 kind 集校验契约段位

planner 出题产物（场景集文件）写盘与验收点 SHALL 按产物场景 kind 集调用既有契约交叉规则（serve_missing_for_scenario_kinds）校验验证契约的 serve/ready 段位齐备性；命中时 SHALL 经既有 verify_contract_missing 通道即时出单条信号，实现期语义遵守在途 verify-contract-precheck-noise-reduction SPEC（info 级 + 同 spec 一次性）；校验 MUST NOT 阻断产物落盘、MUST NOT 触发 planner replan，消费期静态门保留为最后防线。

#### Scenario: kind 集扩容且契约缺 serve 段时写盘即报

- **WHEN** 出题产物场景 kind 集含 api 或 web，且验证契约无 serve 段且 config commands.start 无有效兜底
- **THEN** 产物落盘/验收点即出单条 verify_contract_missing 信号（实现期 info 级一次性），evidence 含 kind 集与缺失段位
- **AND** 消费期静态门不再首见该缺口（同缺口信号去重）

#### Scenario: 契约段位齐备零信号

- **WHEN** 产物 kind 集对应的契约段位齐备，或 kind 集不含需被验证应用可服务的形态
- **THEN** 写盘与验收点零新增信号，既有流程不变

#### Scenario: 契约不可读 fail-open

- **WHEN** 契约文件缺失或解析失败
- **THEN** 前置校验放行不阻断落盘（前置校验只提示不拦截，与消费期门既有 fail-fast 语义分层）

### Requirement: 信号携带定向补段情报

前置校验命中产生的信号 evidence SHALL 携带 scenario_kinds、契约文件路径与缺失段位清单，使代起草处置无需重新考古出题产物。

#### Scenario: 证据可直达补段动作

- **WHEN** 前置校验出信号
- **THEN** evidence 含 kind 集、契约路径与缺失段名，admin/code-fix 可据此直接起草补段
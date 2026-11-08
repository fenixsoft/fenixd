# verify-contract-precheck-noise-reduction 规范

## ADDED Requirements

### Requirement: 实现期契约预检降级与一次性

spec 处于实现流程（implementing 等实现中状态）时，`verify_contract_missing` 前置预检信号 SHALL 降为 info 级且同 spec 一次性（进程内或持久去重，同 spec 实现期内不重复发信号、不召唤 Administrator）；预检文案保留「spec 仍在实现流程中，起草落位即可，勿复位」指引。spec 离开实现流程进入验证相关阶段后，契约仍缺失时按既有 major 语义发信号。

#### Scenario: 实现期单条 info 不召唤

- **WHEN** 首个 SPEC 处于 implementing 且 `.fenix/verify.yaml` 为未裁决模板态，周期巡检执行
- **THEN** 仅首次发一条 info 级提示（文案含实现期指引），不召唤 Administrator；后续巡检周期同 spec 不再发信号

#### Scenario: 进入验证阶段后恢复 major 语义

- **WHEN** 该 spec 离开实现流程且契约仍未裁决
- **THEN** 按既有 `verify_contract_missing` major 语义发信号并召唤 Administrator（既有行为不变）

#### Scenario: 契约已裁决零信号

- **WHEN** 契约在实现期内被起草裁决
- **THEN** 实现期 info 提示与验证期 major 信号均不发生

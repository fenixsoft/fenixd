# alert-lifecycle Specification

## Purpose

spec 附着型信号（如 blocked_stuck）在主体 spec 达到终态（pushed/done）或离开受阻态后自动收口，消除「主体已恢复、信号仍虚报升级」的台账噪音；收口动作沿用既有自动解除闭环的判定与署名，只是把通道对 kind=signal 打开。

## Requirements

### Requirement: 主体终态触发信号收口

对登记为 spec 附着条件族的 kind=signal 记录（含 blocked_stuck），当其主体 spec 状态进入终态（pushed/done）或离开受阻态时，MUST 在周期盘点中标记 handled 并附主体终态时刻注记。

#### Scenario: blocked_stuck 随主体收口

- **WHEN** blocked_stuck 信号 open 且其 spec 已转 pushed
- **THEN** 下一轮盘点将其标记 handled，handled_by 为自动收口署名，注记含 spec 终态时刻

#### Scenario: 主体未终态不收口

- **WHEN** blocked_stuck 信号 open 且其 spec 仍处 blocked
- **THEN** 信号保持原状，升级与派发行为不变

### Requirement: 既有闭环语义不回归

签名安静自愈（SELF_HEAL_SIGNAL_TYPES 三类）、kind=escalation 的既有自动解除、以及 stuck 检测三块卫生逻辑 MUST 行为不变。

#### Scenario: 瞬态类自愈不回归

- **WHEN** daemon_errors 类信号按签名安静判定
- **THEN** 收口行为与现状一致，不受本变更影响
# disposition-reverify-linkage Specification

## ADDED Requirements

### Requirement: env 修复处置闭环自动接续重验

处置链对环境阻塞族信号（verify_env_blocked、verify_env_inconclusive、blocked_stuck）的处置收尾与「处置成功链闭环」事件，SHALL 复用 admin_monitor 既有复位直通道（transition_gate(testing) + 清 error + 入队 verifier）完成 blocked→testing 迁移与重验派发；复位因处置在飞互斥被跳过时 MUST 登记待重评标记并在互斥解除后的下一巡检周期重评消费，MUST NOT 让恢复只能等 blocked_stuck 超时阈值兜底。

#### Scenario: 链上闭环后自动迁回 testing 并入队 verifier

- **WHEN** 环境阻塞族信号的处置链以成功语义闭环（处置回执自述环境已修复），且 spec 处于 blocked
- **THEN** 框架 MUST 完成与 admin_monitor 处置收尾直通道等价的迁移（blocked→testing、清 error、入队 verifier）
- **AND** 链上闭环回执的 unfrozen 语义对 frozen spec 保持既有行为不变

#### Scenario: 互斥跳过后登记待重评

- **WHEN** 复位动作因处置在飞互斥被跳过
- **THEN** 框架 MUST 登记该 spec 的待重评标记，并在互斥解除后的下一巡检周期重评完成迁移，标记消费后清除

#### Scenario: 不满足迁移前提不迁移

- **WHEN** 信号不属环境阻塞族、或 spec 不处于 blocked、或处置结果非已修复语义
- **THEN** MUST NOT 触发迁移（既有行为不变），不得把产品缺陷误迁移回 testing

### Requirement: 处置回执落地校验

「闭环/复位/入队 verifier」类处置动作 SHALL 写可核验句柄（预期 spec 终态、预期 run 类型与判定时间窗），并在窗口内核验 STATE 迁移或对应类型 run 派发落地；未落地 MUST 发升级告警并标记该处置无效，MUST NOT 记成功语义。

#### Scenario: 窗口内落地则成功语义成立

- **WHEN** 判定窗内观察到预期状态迁移或预期类型 run 派发
- **THEN** 处置回执记成功并携带句柄（预期终态与判定窗），供 dashboard 与处置链对账

#### Scenario: 窗口内未落地则告警并标记无效

- **WHEN** 判定窗内无预期迁移亦无预期类型 run 派发
- **THEN** 发升级告警（处置声称与落地不符），处置记录标记无效，不闭环告警链

### Requirement: blocked_stuck 选项桶与白名单补全

blocked_stuck SHALL 注册裁决选项桶（沿用既有单选项桶的注册纪律，选项集含 manual_fixed_reverify；不照搬 verify_env_blocked 桶的既有选项集 _REVISE_SCENARIO_REVERIFY），并按注册桶同源纳入 VERIFY_CHAIN_SIGNAL_TYPES 白名单（blocked_stuck 与既有注册桶 verify_env_blocked 一并补全）；admin 链提示词的选项词表 MUST 按信号桶收窄，MUST NOT 向未注册信号下发 spec 作用域动作词表。

#### Scenario: blocked_stuck 产出 manual_fixed_reverify 可执行

- **WHEN** blocked_stuck 信号的 admin run 产出 manual_fixed_reverify
- **THEN** 选项经桶内精确匹配放行并执行（解冻→testing→入队重验语义），不再以 scoped-no-reverse 拒绝

#### Scenario: 未注册信号不下发 spec 作用域词表

- **WHEN** 某信号未注册任何 spec 作用域选项桶
- **THEN** 该信号的 admin 提示词不含 spec 作用域选项词表（前置防越界，替代事后拒绝）
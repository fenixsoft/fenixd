# adjudication-choice-scope-guard 规格

## ADDED Requirements

### Requirement: 全局信号处置路由防护
系统 SHALL 在执行裁决 choice 前校验信号作用域：spec 为空或占位 'global' 的信号 MUST NOT 执行 spec 作用域 choice。

#### Scenario: 全局信号选到 spec 作用域动作
- **WHEN** 全局信号（spec=null 或 'global'）的处置 choice 为 retry_review 等 spec 作用域动作
- **THEN** 执行被跳过或拒绝，留 INFO/错误日志，信号不被回写为 resolved

#### Scenario: 未注册 signal_type 不再全表反查放行
- **WHEN** 信号的 signal_type 未在 choice 注册表注册且目标 choice 声明为 spec 作用域
- **THEN** 拒绝执行，而非经跨信号全表反查兜底放行

### Requirement: 失败不回写 resolved
choice 执行失败时系统 SHALL NOT 将信号回写为 handled=true / result=resolved。

#### Scenario: choice 执行失败
- **WHEN** _apply_choice_execution 执行 choice 返回失败
- **THEN** 信号改记 failed（保留待重审），处置记录 error 字段写入失败原因

### Requirement: 执行结果留痕
系统 SHALL 把 choice 执行结果写入告警记录 action_taken 与 result 字段。

#### Scenario: 执行结果留痕
- **WHEN** choice 执行（无论成败）完成
- **THEN** 告警记录 action_taken 记录动作名、result 记录执行终态（不再是恒 null）

### Requirement: 全局信号保留可用动作
对全局信号过滤 spec 作用域 choice 后，系统 SHALL 保留至少一个非 spec 作用域的可执行 choice（如『确认自愈/继续观察』类），避免全局信号滞留 pending 无路可走。

#### Scenario: 过滤后仍有可用动作
- **WHEN** 全局信号的 choices 被作用域过滤
- **THEN** 非作用域 choice（或全局等价动作）仍可执行并正常收口
## ADDED Requirements

### Requirement: 手动唤起信号透传底层 signal_type

daemon 消费 `.fenix/admin_invoke_request.json` 构造 Administrator 处置信号时，MUST 反查该 spec 最近一条未处置（非 handled）的 SIGNAL/ESCALATION 记录（按 created 取最新，MUST 排除 `signal_type == "manual-intervention"` 的手动通道自产记录），取其 `signal_type` 写入信号的 `underlying_signal_type` 字段；查不到时该字段为 None。信号顶层 `signal_type` MUST 保持 `manual-intervention`（store 记录、节流锚点、活动区展示语义不变）。

#### Scenario: 存在未处置信号时透传底层类型
- **WHEN** spec 存在一条未处置的 `verify_env_blocked` 信号记录，人工经 Dashboard 唤起 Administrator
- **THEN** 构造的处置信号 `signal_type=manual-intervention` 且 `underlying_signal_type=verify_env_blocked`

#### Scenario: 无可反查信号时缺省 None
- **WHEN** spec 无任何未处置信号记录时被手动唤起
- **THEN** 处置信号 `underlying_signal_type` 为 None，顶层 `signal_type` 仍为 `manual-intervention`，唤起流程不报错

#### Scenario: 手动通道自产记录不被误反查
- **WHEN** spec 存在一条未处置的 `manual-intervention` ESCALATION 记录（上次手动派发失败遗留），其后另有一条未处置的 `verify_env_blocked` 信号记录，人工再次唤起
- **THEN** `underlying_signal_type=verify_env_blocked`（manual-intervention 记录被排除，不作为底层类型）

### Requirement: 处置收尾自动复位判定门感知透传类型

处置收尾自动复位的判定（`result ∈ {resolved, partially-resolved}` 且信号类型命中 `DISPOSITION_AUTO_RESET_SIGNAL_TYPES`）MUST 扩展为：`signal_type` 或 `underlying_signal_type` 任一命中即触发。其余语义（escalated 不复位、复位守卫 frozen/非 blocked、业务侧车字段不清零）MUST 保持不变。

#### Scenario: 透传 env 族信号处置成功后自动复位
- **WHEN** `underlying_signal_type=verify_env_blocked` 的手动唤起处置完成且 result=resolved
- **THEN** 命中自动复位：实现分支已合并走 testing 直通道重验，否则回 ready，spec 不再悬置 blocked

#### Scenario: 底层类型不在复位集合时不复位
- **WHEN** `underlying_signal_type=orphaned_state`（不属自动复位集合）的手动唤起处置完成且 result=resolved
- **THEN** 不触发该自动复位路径（orphaned_state 走其既有独立复位路径），行为与改造前一致

#### Scenario: 节流与记录零回归
- **WHEN** 同一 spec 短时间内两次手动唤起
- **THEN** 手动通道 store 落痕（disposition/escalation）仍按 `manual-intervention` 类型记录，自动通道既有节流（按其自身 signal_type 判定）不受影响，透传字段不参与节流、不产生重复告警

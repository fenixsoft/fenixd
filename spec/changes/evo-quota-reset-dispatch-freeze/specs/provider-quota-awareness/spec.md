# provider-quota-awareness Specification

## ADDED Requirements

### Requirement: 限流重置时间驱动的 provider 冻结

provider 返回携带重置时间戳的限流响应时，框架 MUST 解析该时间戳，并把该 provider 的派发冷却到期时间取 max(既有固定冷却时长, 重置时刻)；MUST NOT 在重置时刻前对该 provider 派发新的 run。

#### Scenario: 冻结生效至重置时刻

- **WHEN** provider 返回含重置时间戳的 RATE_LIMIT 响应
- **THEN** 该 provider 进入派发冻结，冻结期内无新 run 被派往该 provider，重置时刻后恢复正常派发

#### Scenario: 重置早于固定冷却时取固定冷却

- **WHEN** 报文重置时刻早于既有固定冷却到期时间
- **THEN** 冷却到期时间按既有固定时长执行，不因重置时刻提前

### Requirement: 冻结期派发廉价失败与汇总告警单条化

冻结期内的派发请求 MUST 廉价失败（不发起真实 run、不计入失败重试与预算计数），并 MUST 以单条汇总告警呈现冻结状态（含重置时刻），MUST NOT 逐 run 产生独立失败告警。

#### Scenario: 冻结期派发被拦截且告警不重复

- **WHEN** 冻结期内多个 spec 的派发命中该冻结 provider
- **THEN** 各派发廉价失败，告警面只维护一条汇总告警并随命中次数更新计数

#### Scenario: 冻结解除后告警收口

- **WHEN** 到达重置时刻冻结解除
- **THEN** 汇总告警按既有告警生命周期收口，不留悬置条目
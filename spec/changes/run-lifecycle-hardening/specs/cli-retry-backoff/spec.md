# cli-retry-backoff

## ADDED Requirements

### Requirement: 连续秒级失败的退避冷却

同一 spec 的 run 在进程存活时长低于秒挂判定阈值（默认 60 秒，配置键 `agents.instant_fail_threshold_seconds`）即死亡、且连续失败次数达到阈值（默认 3 次，配置键 `agents.instant_fail_cooldown_after`）时，daemon MUST 对该 spec 启动冷却：冷却时长默认 300 秒（配置键 `agents.instant_fail_cooldown_seconds`），冷却期内所有 implementer/fast-track/repair 派发请求 MUST 被跳过（记 DEBUG 日志，不消耗实现预算、不启动进程）；冷却到期后自动恢复正常调度。

#### Scenario: 连续秒挂触发冷却

- **WHEN** 某 spec 的 run 连续 3 次在 60 秒内死亡（如 Exit 143 秒挂）
- **THEN** 第 3 次失败后该 spec 进入 300 秒冷却，期间后续派发请求被跳过且不产生新 claude 进程

#### Scenario: 冷却到期自动恢复

- **WHEN** 冷却期（300 秒）届满后调度器再次处理该 spec
- **THEN** 正常派发，冷却状态清除，连续失败计数从 0 重新累计

#### Scenario: 非连续失败不累积

- **WHEN** 某 spec 在两次秒挂之间出现一次成功 run 或一次存活超过阈值的失败 run
- **THEN** 连续计数归零，后续重新累计

### Requirement: 秒挂风暴告警

冷却首次触发时，daemon MUST 发出一条 major 级人工告警（signal_type 如 `instant_fail_storm`），说明 spec 名、连续失败次数与冷却安排；同一 spec 的重复冷却在告警冷却窗口（沿用既有 15 分钟 throttle）内 MUST NOT 重复告警。

#### Scenario: 首次冷却告警

- **WHEN** 某 spec 首次进入秒挂冷却
- **THEN** admin_alerts 出现一条 major 告警，包含 spec 名与「3 次连续秒挂 → 冷却 300s」的说明

#### Scenario: 重复冷却不刷屏

- **WHEN** 同一 spec 在 15 分钟内第二次进入冷却
- **THEN** 不产生第二条告警（被既有 throttle 机制抑制）

### Requirement: 与 provider 熔断正交

秒挂退避是 spec 级调度冷却，MUST NOT 改变 provider 熔断（4xx circuit）语义：秒挂计数不进入 provider 熔断窗口，provider 熔断也不重置 spec 秒挂计数。

#### Scenario: 两机制互不干扰

- **WHEN** 某 spec 因秒挂进入冷却，同时另一 spec 因 4xx 触发 provider 熔断
- **THEN** 两机制各自独立生效与解除，互不重置对方计数

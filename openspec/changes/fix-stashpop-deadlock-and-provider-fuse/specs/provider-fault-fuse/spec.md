## ADDED Requirements

### Requirement: provider 4xx 滚动窗口熔断
agent_runner 对同一 provider 维护熔断状态：滚动窗口（默认 5 分钟）内累计 HTTP 4xx（400/401/404）达阈值（默认 3 次）时，将该 provider 标记为 `circuit_open`，进入冷却期（默认 30 分钟）。窗口/阈值/冷却时长作为常量或可配置项，至少体现在代码常量处。

#### Scenario: 达阈值触发熔断
- **WHEN** 某 provider 在 5 分钟内对 3 次请求返回 400/401/404（如网关模型下线返回的 unrecognized_model）
- **THEN** agent_runner 将该 provider 标记 circuit_open，后续派发不再启动 claude 进程

### Requirement: 熔断期间不派发、不计入 spec 连续失败
熔断期间任何需要该 provider 的派发（implementer/verifier/planner）直接返回明确错误（如 `provider circuit open: <name> (HTTP 404 x3)`），且该失败不计入 spec 的 `_retry_count` / `_merge_streak`，不触发状态机回到 ready（spec 保持当前状态），避免故障窗口内反复重派与 autostash 积累。

#### Scenario: 熔断期 spec 状态稳定
- **WHEN** provider 处于 circuit_open 时队列尝试派发该 spec 的 implementer
- **THEN** 派发失败并记录 `provider circuit open` 错误，spec 状态不变、不进入重试计数、不产生新 worktree / autostash

### Requirement: 冷却后自动恢复
冷却期结束后首个派发尝试作为半开探针：若网关返回 200，闭合熔断（circuit closed）并正常执行该派发；若仍 4xx，重新进入冷却期并继续拦截。5xx 与网络错误不触发熔断，按既有重试逻辑处理。

#### Scenario: 网关恢复后自动闭合
- **WHEN** circuit_open 的 provider 冷却期结束后网关已恢复（curl 实测 200），队列再次派发
- **THEN** 该派发正常执行且 provider 状态恢复 closed，后续派发不再被拦截

### Requirement: 故障可见性
熔断状态与原因须在错误信息中明确呈现：spec 的 error 字段、admin_monitor 告警、dashboard 运行错误列均能区分「provider 熔断（含 name、HTTP code、次数）」与「spec 自身实现问题」，便于人工判断是充值/换模型还是修代码。

#### Scenario: 告警可读性
- **WHEN** 触发熔断或熔断期派发失败
- **THEN** 错误文本包含 `provider circuit open: <provider-name> (HTTP <code> x <count>)` 及冷却剩余时间（或到期时间）
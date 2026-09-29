<!-- knowledge: capability=failover-dispatch rev=1 sources=spec/archive/2026-09-02-add-provider-failover -->

# provider 故障切换派发（failover 链推进与可观测）

attempt 失败后的链推进决策与留痕：切换类错误驱动候选链前进，全程以 provider_marker 与 switch 日志留痕。

## 规则

- `classify_switch_error()` 负责错误分类：HTTP 5xx 与连接类异常属瞬断类，先走原地退避（见 [provider-transient-backoff](provider-transient-backoff.md)），原地预算耗尽才进入本能力的链推进；`unrecognized_model` 属确定性模型失败，立即沿链推进、不重派（见 [model-chain-health-probe](model-chain-health-probe.md)）。
- 链推进发生在同一 run 内：后续 attempt 自动使用链上下一未冷却候选（switch 冷却期内的候选被跳过），不终止 run、不以同因重新派发整个 run。
- 配额/鉴权类 HTTP 4xx 不纳入链前进，维持 provider 熔断语义处理（见 [provider-fault-fuse](provider-fault-fuse.md)）。
- 链上所有候选均处于 switch 冷却期时，attempt 直接失败并带 `chain_exhausted` 标记：不创建进程、不计入 spec 重试消耗。
- 可观测契约：每个 attempt 启动时向 run jsonl 追加 provider_marker 行（provider / model / chain_index）；AgentRunResult 携带 provider_used / model_used；跨 attempt 切换输出 INFO 级「provider switched」日志（含 spec 名与新旧 provider，模型名变化时附 `model_changed: <old>→<new>`）。
- 单 provider 当日 attempt 计数超过 `pm.failover.daily_attempts_warn` 时打 WARNING，当日只告警一次。

## 溯源

- [2026-09-02 add-provider-failover](spec/archive/2026-09-02-add-provider-failover/) — 建立切换类错误分类、链推进与全链冷却失败语义，以及 provider_marker / provider switched / 高频告警三件可观测契约

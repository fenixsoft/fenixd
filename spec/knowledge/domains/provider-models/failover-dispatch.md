<!-- knowledge: capability=failover-dispatch rev=2 sources=spec/archive/2026-09-02-add-provider-failover,spec/archive/2026-09-30-add-code-review-concurrency-and-429-resilience -->

# provider 故障切换派发（failover 链推进与可观测）

attempt 失败后的链推进决策与留痕：切换类错误驱动候选链前进，全程以 provider_marker 与 switch 日志留痕。

## 规则

- `classify_switch_error()` 负责错误分类，429 限流三形态（HTTP 429 / 错误码 `[1302]` / error type `rate_limit`）先于瞬断与 4xx 解析判定（见 [ADR-201](../../adr/ADR-201-ratelimit-switch-channel-independent-cooldown-no-fuse-double-count.md)）；HTTP 5xx 与连接类异常属瞬断类，先走原地退避（见 [provider-transient-backoff](provider-transient-backoff.md)），原地预算耗尽才进入本能力的链推进；`unrecognized_model` 属确定性模型失败，立即沿链推进、不重派（见 [model-chain-health-probe](model-chain-health-probe.md)）。
- 429 限流命中走独立限流冷却：复用 switch 冷却机制，独立常量 `PROVIDER_RATELIMIT_COOLDOWN_SECONDS`（缺省 300s，不与 switch 冷却共用键；本期不做配置键，调参改常量），冷却期内链选择跳过该候选——不启动进程、不烧 429。
- 429 不计入 `PROVIDER_CIRCUIT_4XX` 熔断计数：限流是暂时性配额压力，与配额/鉴权故障的 30min 熔断语义不同，双重计数会放大冷却；配额/鉴权类 HTTP 4xx 维持 provider 熔断语义处理、不纳入链前进（见 [provider-fault-fuse](provider-fault-fuse.md)）。
- 链推进发生在同一 run 内：后续 attempt 自动使用链上下一未冷却候选（switch/限流冷却期内的候选被跳过），并继续携带 `--resume <session_id>` 续跑原会话；不终止 run、不以同因重新派发整个 run。
- 链上所有候选均处于 switch/限流冷却期时，attempt 直接失败并带 `chain_exhausted` 标记：不创建进程、不计入 spec 重试消耗。
- 429 打死的 run 自动重派一次：run 终态归因为 429 限流（terminal_reason 为 api_error 且错误文本命中 429 分类）时，runner 只登记重派意图不执行重派，由唯一生产调用方的收场分支在该 provider 冷却到期后执行；重派携带原 run 上下文幂等续做（code-review 车道复用原 manifest，已落盘分片经聚合读侧按 file 去重消费、已审文件不重审），受既有预算与重试上限守卫——重派计一次 attempt，超上限按既有失败路径收场升级人工，不无限重派（对禁同因重派的有界例外，见 [ADR-202](../../adr/ADR-202-ratelimit-terminal-redispatch-intent-registration-consumer-split.md)）。
- 重派 run 在运行记录中标注「429 限流重派」缘由，供取证。
- 可观测契约：每个 attempt 启动时向 run jsonl 追加 provider_marker 行（provider / model / chain_index）；AgentRunResult 携带 provider_used / model_used；跨 attempt 切换输出 INFO 级「provider switched」日志（含 spec 名与新旧 provider，模型名变化时附 `model_changed: <old>→<new>`）。
- 单 provider 当日 attempt 计数超过 `pm.failover.daily_attempts_warn` 时打 WARNING，当日只告警一次。

## 溯源

- 2026-09-02 add-provider-failover（spec/archive/2026-09-02-add-provider-failover） — 建立切换类错误分类、链推进与全链冷却失败语义，以及 provider_marker / provider switched / 高频告警三件可观测契约
- 2026-09-30 add-code-review-concurrency-and-429-resilience（spec/archive/2026-09-30-add-code-review-concurrency-and-429-resilience） — 429 限流纳入切换类分类（三形态判定先于瞬断/4xx、独立限流冷却缺省 300s、不计 4xx 熔断双计数），新增限流打死 run 冷却到期自动重派一次（意图登记/唯一消费方/幂等续做/预算守卫/留痕标注）

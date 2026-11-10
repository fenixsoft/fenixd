<!-- knowledge: capability=failover-dispatch rev=7 sources=spec/archive/2026-09-02-add-provider-failover,spec/archive/2026-09-30-add-code-review-concurrency-and-429-resilience,spec/archive/2026-10-06-evo-add-code-review-ratelimit-resume,spec/knowledge/_inbox/done/memory-distill-diagnostic-signatures.md,spec/changes/add-maintenance-lane-provider-failover -->

# provider 故障切换派发（failover 链推进与可观测）

attempt 失败后的链推进决策与留痕：切换类错误驱动候选链前进，全程以 provider_marker 与 switch 日志留痕。

## 规则

- `classify_switch_error()` 负责错误分类，429 限流三形态（HTTP 429 / 错误码 `[1302]` / error type `rate_limit`）先于瞬断与 4xx 解析判定（见 [ADR-201](../../adr/ADR-201-ratelimit-switch-channel-independent-cooldown-no-fuse-double-count.md)）；HTTP 5xx 与连接类异常属瞬断类，先走原地退避（见 [provider-transient-backoff](provider-transient-backoff.md)），原地预算耗尽才进入本能力的链推进；`unrecognized_model` 属确定性模型失败，立即沿链推进、不重派（见 [model-chain-health-probe](model-chain-health-probe.md)）。
- 429 限流命中走独立限流冷却：复用 switch 冷却机制，独立常量 `PROVIDER_RATELIMIT_COOLDOWN_SECONDS`（缺省 300s，不与 switch 冷却共用键；本期不做配置键，调参改常量），冷却期内链选择跳过该候选——不启动进程、不烧 429。
- 429 不计入 `PROVIDER_CIRCUIT_4XX` 熔断计数：限流是暂时性配额压力，与配额/鉴权故障的 30min 熔断语义不同，双重计数会放大冷却；配额/鉴权类 HTTP 4xx 维持 provider 熔断语义处理、不纳入链前进（见 [provider-fault-fuse](provider-fault-fuse.md)）。
- 切链闸门 MUST 复用结构化双源信号（`runner._switch_signal_text`：降噪后的 error 文本 + result 事件的 `result` 文本 + `api_error_status`，429 归一化后追加 `HTTP 429` 形态）：`_denoise_stderr` 会把 `[claude-code:...]` 诊断行剔除、429/拒模型正文只存在于 result 事件，若闸门只读降噪文本会把切换类错误误判为「非切换」→ 链指针不动、冷却不记、后续 attempt 反复打链首（2026-11-09 glm 周/月额度耗尽事故的直接机制）；判定 MUST NOT 回填 `[claude-code:unrecognized_model]` stderr 噪声行（该行由模型名唯一决定、成功 run 同样在场）。
- 链推进发生在同一 run 内：后续 attempt 自动使用链上下一未冷却候选（switch/限流冷却期内的候选被跳过），并继续携带 `--resume <session_id>` 续跑原会话；不终止 run、不以同因重新派发整个 run。
- 链上所有候选均处于 switch/限流冷却期时，attempt 直接失败并带 `chain_exhausted` 标记：不创建进程、不计入 spec 重试消耗。
- 429 打死的 run 自动重派一次：run 终态归因为 429 限流（归因双源：降噪后错误文本命中 429 分类先行，未命中回退 result 事件的 `api_error_status` / result 文本判定）时，runner 只登记重派意图不执行重派，由消费侧在该 provider 冷却到期后执行——code-review 车道的消费入口为手动与周期两车道共享配额的统一入口（见 [repo-review-ratelimit-resume](../code-review-lane/repo-review-ratelimit-resume.md)）；重派幂等续做（code-review 车道剃余续跑只跑剩余文件，聚合读侧按 file 去重仍作兜底），受既有预算与重试上限守卫——重派计一次 attempt，超上限按既有失败路径收场升级人工，不无限重派（对禁同因重派的有界例外，见 [ADR-202](../../adr/ADR-202-ratelimit-terminal-redispatch-intent-registration-consumer-split.md)、[ADR-237](../../adr/ADR-237-ratelimit-attribution-dual-source-shared-quota-shaved-resume.md)）。
- 重派 run 在运行记录中标注「429 限流重派」缘由，供取证。
- 可观测契约：每个 attempt 启动时向 run jsonl 追加 provider_marker 行（provider / model / chain_index）；AgentRunResult 携带 provider_used / model_used；跨 attempt 切换输出 INFO 级「provider switched」日志（含 spec 名与新旧 provider，模型名变化时附 `model_changed: <old>→<new>`）。
- 单 provider 当日 attempt 计数超过 `pm.failover.daily_attempts_warn` 时打 WARNING，当日只告警一次。
- 链推进契约覆盖两个环：dispatch attempt 环与八条 LLM 车道（六条维护车道 administrator / arbiter / self-review / evolution / code-review / code-fix + 两条判官范式车道 spec-review / dispute-judge）的单 run 候选环。两环共用同一套链选择/切换判定/冷却/记账原语，候选环本体单一真源为 `AgentRunner._run_agent_with_chain_failover`（见 [ADR-343](../../adr/ADR-343-maintenance-lane-candidate-ring-single-source-in-runner.md)）；车道侧链解析与角色回退顺序、换候选与冷却细节、marker 真实链下标、429 终局重派按链解析等契约见 [maintenance-lane-provider-failover](maintenance-lane-provider-failover.md)。
- 触发面是「失败」不是「挂」：链推进由 attempt 失败信号（错误/非零退出）驱动，网关「连得上但不响应」的 TCP 黑洞不产生失败信号、不触发任何链推进或退避——run 以约 1 轮/10 分钟的蠕动节奏耗到超时监督上限。黑洞型故障只有超时监督能兜底，取证时勿以「为何不 failover」归因，先确认 provider 是否处于黑洞形态。

## 溯源

- 2026-09-02 add-provider-failover（spec/archive/2026-09-02-add-provider-failover） — 建立切换类错误分类、链推进与全链冷却失败语义，以及 provider_marker / provider switched / 高频告警三件可观测契约
- 2026-09-30 add-code-review-concurrency-and-429-resilience（spec/archive/2026-09-30-add-code-review-concurrency-and-429-resilience） — 429 限流纳入切换类分类（三形态判定先于瞬断/4xx、独立限流冷却缺省 300s、不计 4xx 熔断双计数），新增限流打死 run 冷却到期自动重派一次（意图登记/唯一消费方/幂等续做/预算守卫/留痕标注）
- 2026-10-06 add-code-review-ratelimit-resume（spec/archive/2026-10-06-evo-add-code-review-ratelimit-resume） — 限流终局归因改双源（result 事件兜底）、重派消费由唯一周期消费方改为手动+周期双车道共享配额统一入口、code-review 车道重派由复用原 manifest 全量重跑改为剃余续跑只跑剩余文件
- 2026-11-04 memory-distill-diagnostic-signatures（spec/knowledge/_inbox/done/memory-distill-diagnostic-signatures.md） — 折叠 failover 触发面判读签名：只认失败不认挂，TCP 黑洞不触发链推进，run 蠕动到监督上限须靠超时监督兜底
- 2026-11-10 事故修复（core/agent_runner/runner.py，commit `d08d2fbd0`） — 修复「429/拒模型只出现在 result 事件时 attempt 环切链闸门恒假、链永不前进」缺陷：抽 `_switch_signal_text` 为切链判定单一真源（error 文本 + result 文本 + `api_error_status`），`_record_4xx_or_transient` 增拒模型 result 事件双源回退；补两条「降噪文本 + 结构化 429」回归用例。同时标注维护车道/判官范式车道暂无链 failover 的现状边界（接入见 spec/changes/add-maintenance-lane-provider-failover）
- 2026-11-10 add-maintenance-lane-provider-failover（spec/changes/add-maintenance-lane-provider-failover） — 候选环接入六条维护车道与两条判官范式车道（判定/冷却/分类与 dispatch 环共用单一原语，marker 真实链下标，非切换错误不换候选，未配链 fail-open 单发）；429 重派意图 additive 携带 chain_len/失败候选、复跑按当时冷却重新解析链不固定复用链首；车道环选点加 skip_indexes 本地记账防簿记缺失时重复候选
- 2026-11-10 add-maintenance-lane-provider-failover 验证修复（原地打回第 1 轮，同 SPEC findings.md F8） — 拒模型记账词表扩纳网关「Model not found: <model>」HTTP 400 正文形态（与切换类词表第三条共用收窄正则单源 `MODEL_NOT_FOUND_TEXT_PATTERN`）：车道候选环拒模型记账 WARNING 恢复、dispatch `_record_4xx_or_transient` 该形态不再误入 4xx 熔断计数；本地错误形态不命中、「拒模型 ⊆ 切换类」真子集保持
- 2026-11-10 add-maintenance-lane-provider-failover（spec/changes/add-maintenance-lane-provider-failover/） — 能力页分治：车道侧规则（八车道候选环接入/链路可观测/429 重派按链解析）拆分至独立能力页 maintenance-lane-provider-failover，本页保留 dispatch attempt 环口径与两环适用面声明

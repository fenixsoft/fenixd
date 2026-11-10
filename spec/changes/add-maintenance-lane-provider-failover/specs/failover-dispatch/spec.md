# spec-failover-dispatch（delta）

> 基线：`spec/archive/2026-09-30-add-code-review-concurrency-and-429-resilience/specs/failover-dispatch/spec.md`
> 本次变更：切换类错误的链推进契约从 dispatch attempt 环扩展到六条 LLM 维护车道与两条判官范式车道（spec-review / dispute-judge）的单 run 候选环（2026-11-09 glm 周/月额度耗尽事故第二断点；判官范式车道并入为 2026-11-10 09:41 用户确认）。

## MODIFIED Requirements

### Requirement: 切换类错误驱动链前进
`classify_switch_error()` SHALL 将 `unrecognized_model` 文本、HTTP 5xx、连接类异常、**429 限流错误**（HTTP 429 / 错误码 `[1302]` / error type `rate_limit`）分类为切换类错误。**适用面**：dispatch attempt 环与维护/判官范式车道单 run 候选环一致——六条 LLM 维护车道（administrator / arbiter / self-review / evolution / code-review / code-fix）与两条判官范式车道（spec-review / dispute-judge，`runner.py` 的 `run_spec_review` / `run_dispute_judge` 镜像方法）在单 run 内以切换类错误失败时 MUST 自动换链上下一个未冷却候选（上限 = 链长），429 命中时该 provider SHALL 进入限流冷却（复用 switch 冷却机制，默认 300s——独立常量 `PROVIDER_RATELIMIT_COOLDOWN_SECONDS`，本期不做配置键），冷却期内链选择 MUST 跳过该候选；429 MUST NOT 计入 `PROVIDER_CIRCUIT_4XX` 熔断计数。配额/鉴权类 4xx 维持既有 provider-fault-fuse 熔断语义，不纳入链前进。切换判定 MUST 使用结构化双源（error 文本 + result 事件 `api_error_status`/`result` 文本），MUST NOT 只读降噪后的 error 文本，MUST NOT 回填 `[claude-code:unrecognized_model]` 诊断噪声行。

#### Scenario: unrecognized_model 触发切换
- **WHEN** attempt 返回 rc!=0 且 stderr 含 `[claude-code:unrecognized_model] {"model":"deepseek-v4-flash"}`
- **THEN** 该 provider 进入 switch 冷却（默认 300s），下一 attempt 使用链上下一候选并 resume 原会话

#### Scenario: 4xx 不推进链
- **WHEN** attempt 因可解析 HTTP 4xx（400/401/403/404）失败
- **THEN** 走既有 4xx 熔断计数路径，链指针不动

#### Scenario: 429 限流触发冷却
- **WHEN** attempt 以 `API Error: Request rejected (429) · [1302][您的账户已达到速率限制...]` 失败
- **THEN** 该 provider 进入限流冷却（默认 300s），同 run 下一 attempt 使用链上下一候选；该失败不计入 4xx 熔断计数

#### Scenario: 冷却期内其它派发跳过该候选
- **WHEN** 某 provider 处于 429 限流冷却期，另一 run 发起派发
- **THEN** 链选择跳过该候选（不启动 claude、不烧 429），选用未冷却候选

#### Scenario: 全链冷却时保持失败语义
- **WHEN** 链上所有候选均处于 switch/限流冷却期
- **THEN** attempt 直接失败返回（带 chain_exhausted 标记），不创建进程、不计入 spec 重试消耗

#### Scenario: 维护车道 429 换候选
- **WHEN** 维护车道（如 code-review）首候选以 429 失败且 429 文案只出现在 result 事件（`api_error_status=429`），链上另有未冷却候选
- **THEN** 本 run 内换下一候选执行，首候选进入 300s 限流冷却，provider_marker 记录 `chain_index=0/1, chain_len=2`

#### Scenario: 判官范式车道 429 换候选
- **WHEN** spec-review 或 dispute-judge 车道首候选以 429 失败（429 文案只在 result 事件），链上另有未冷却候选
- **THEN** 本 run 内换下一候选执行，`AgentRunResult.provider_used` 为第二候选，首候选进入 300s 限流冷却

## ADDED Requirements

### Requirement: 维护/判官范式链路可观测与 429 重派按链解析
六条 LLM 维护车道与两条判官范式车道（spec-review / dispute-judge）的 `provider_marker` SHALL 如实记录实际候选的 `chain_index` 与 `chain_len`（链长；MAY 追加 `attempt` 序号），链下标 MUST NOT 再硬编码为 0、链长 MUST NOT 再硬编码为 1。终局归因为 429 时，重派意图 SHALL 携带链信息（`chain_len`、失败候选）；重派消费复跑时 MUST 重新解析链并按冷却跳过候选（MUST NOT 固定复用首跑链首），重派上限仍为 `RATELIMIT_REDISPATCH_MAX=1`。

#### Scenario: 维护车道 marker 链下标真实
- **WHEN** code-review 角色配置双候选链且首跑使用第二候选
- **THEN** run jsonl 的 provider_marker 记录 `chain_index=1, chain_len=2`

#### Scenario: 429 重派重新解析链
- **WHEN** 某 code-review run 全链 429 终态、进入重派流程
- **THEN** 冷却到期后复跑按当时链状态与冷却标记重新选候选（不固定链首），意图/日志含链信息，重派至多一次

## Deliverables

- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify

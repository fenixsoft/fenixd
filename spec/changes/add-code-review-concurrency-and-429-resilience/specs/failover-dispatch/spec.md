# spec-failover-dispatch（delta）

> 基线：`spec/archive/2026-09-02-add-provider-failover/specs/failover-dispatch/spec.md`（2026-09-24 429 事故：bigmodel 网关 `Request rejected (429) · [1302]` 打死 manual_full run，429 不在任何容错分类里）。

## MODIFIED Requirements

### Requirement: 切换类错误驱动链前进
`classify_switch_error()` SHALL 将 `unrecognized_model` 文本、HTTP 5xx、连接类异常、**429 限流错误**（HTTP 429 / 错误码 `[1302]` / error type `rate_limit`）分类为切换类错误；attempt 以切换类错误失败时，同 run 后续 attempt MUST 自动使用链上下一未冷却候选，并继续携带 `--resume <session_id>` 续跑原会话。429 命中时该 provider SHALL 进入限流冷却（复用 switch 冷却机制，默认 300s，可配），冷却期内链选择跳过该候选；429 MUST NOT 计入 `PROVIDER_CIRCUIT_4XX` 熔断计数（限流是暂时性配额压力，与配额/鉴权故障的 30min 熔断语义不同，双重计数会放大冷却）。配额/鉴权类 4xx 维持既有 provider-fault-fuse 熔断语义，不纳入链前进。

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

## ADDED Requirements

### Requirement: 429 打死的 run 自动重派
run 终态归因为 429 限流（`terminal_reason` 为 api_error 且错误文本命中 429 分类）时，框架 SHALL 在该 provider 冷却到期后自动重派该 run 一次（携带原 run 上下文/产物续做语义：code-review 车道复用原 manifest，已落盘分片经聚合口径幂等消费）；重派 MUST 受既有预算与重试上限守卫（重派计一次 attempt，超上限按既有失败路径收场升级人工，MUST NOT 无限重试）。运行记录 SHALL 标注「429 限流重派」缘由以便取证。

#### Scenario: 冷却到期自动重派
- **WHEN** 某 code-review run 被 429 打死且未超重派上限
- **THEN** provider 冷却到期后框架自动以原 manifest 重派，运行记录标注重派缘由

#### Scenario: 重派超上限按既有失败收场
- **WHEN** 重派后的 run 仍被 429 打死且已达重试上限
- **THEN** 按既有失败路径收场（升级人工/告警），MUST NOT 再次重派

#### Scenario: 重派幂等消费已有产物
- **WHEN** 重派的 code-review run 启动时原 run 已有分片/主产物落盘
- **THEN** 聚合读侧按 file 去重消费，已审文件不重审（提示词既有「不重审」纪律约束读侧口径一致）

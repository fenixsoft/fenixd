# spec-failover-dispatch

## ADDED Requirements

### Requirement: 切换类错误驱动链前进
`classify_switch_error()` SHALL 将 `unrecognized_model` 文本、HTTP 5xx、连接类异常分类为切换类错误；attempt 以切换类错误失败时，同 run 后续 attempt MUST 自动使用链上下一未冷却候选，并继续携带 `--resume <session_id>` 续跑原会话。配额/鉴权类 4xx 维持既有 provider-fault-fuse 熔断语义，不纳入链前进。

#### Scenario: unrecognized_model 触发切换
- **WHEN** attempt 返回 rc!=0 且 stderr 含 `[claude-code:unrecognized_model] {"model":"deepseek-v4-flash"}`
- **THEN** 该 provider 进入 switch 冷却（默认 300s），下一 attempt 使用链上下一候选并 resume 原会话

#### Scenario: 4xx 不推进链
- **WHEN** attempt 因可解析 HTTP 4xx 失败
- **THEN** 走既有 4xx 熔断计数路径，链指针不动

#### Scenario: 全链冷却时保持失败语义
- **WHEN** 链上所有候选均处于 switch 冷却期
- **THEN** attempt 直接失败返回（带 chain_exhausted 标记），不创建进程、不计入 spec 重试消耗

### Requirement: 切换可观测
每次 attempt 启动时 SHALL 向 run jsonl 追加 provider_marker 行（provider/model/chain_index）；AgentRunResult SHALL 携带 provider_used/model_used；跨 attempt 的切换 MUST 输出 INFO 级 "provider switched" 日志（含 spec 名与新旧 provider）；每 provider 当日 attempt 计数超过 `pm.failover.daily_attempts_warn` 时打 WARNING。

#### Scenario: 产物可追溯
- **WHEN** 某 attempt 在第二候选上运行
- **THEN** 其 run jsonl 首部含 provider_marker 指明 chain_index=1 与该 provider 的三件套摘要

#### Scenario: 切换留痕
- **WHEN** attempt2 相比 attempt1 发生 provider 切换
- **THEN** daemon 日志出现 "provider switched inferaiapi.com → aliyun for '<spec>'"

#### Scenario: 高频告警
- **WHEN** 某 provider 当日 attempt 数超过 daily_attempts_warn
- **THEN** 输出 WARNING 日志且当日只告警一次

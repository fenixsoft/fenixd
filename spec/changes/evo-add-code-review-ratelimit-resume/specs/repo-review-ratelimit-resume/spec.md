# repo-review-ratelimit-resume 能力规格（delta）

## ADDED Requirements

### Requirement: 429 归因双源

审查 run 以非零退出终局且 stderr 文本分类未命中限流形态时，框架 SHALL 回退读取 run jsonl result 事件（api_error_status=429 或 result 文本命中限流形态）判定限流终局，并照常登记 ratelimit_redispatch 意图与标注 run。

#### Scenario: stderr 全噪音仍归因

- **WHEN** 429 文案仅存在于 result 事件、stderr 降噪后为 Exit code: 1
- **THEN** 意图登记成功（run jsonl 出现 type: ratelimit_redispatch）且 provider 进入冷却

### Requirement: 手动通道消费限流重派

手动审查触发 worker SHALL 与周期 worker 同样消费 ratelimit_redispatch 意图：沿用 300 秒冷却、重派上限 1 与单飞让位语义， SHALL NOT 重复派发。

#### Scenario: 手动审查死于 429 后自动重派

- **WHEN** 手动触发的审查 run 死于限流终局
- **THEN** 冷却期满后自动调度重派，且窗口内不产生第二次重派

### Requirement: 分片续跑

限流重派 SHALL 把 manifest 剃成「原清单减去已落账分片覆盖的文件」后执行，redispatch_of 链路 SHALL 保留；「本轮累计覆盖=完整 manifest」之前 SHALL NOT 触发全仓快照核销。

#### Scenario: 续跑只跑剩余文件

- **WHEN** 原审查 16 片仅落 4 片后触发重派
- **THEN** 重派 manifest 仅含剩余文件（约 202/270）且标注 redispatch_of
- **AND** 累计覆盖不完整时快照核销保持锁定

### Requirement: 二次全仓叠加防护

手动 full 审查触发时，若台账 open 条数超过阈值，框架 SHALL 返回确认态（对齐 trigger-ack 409 守卫先例）而非直接开跑，阈值可配置。

#### Scenario: 上一轮未消化完时需确认

- **WHEN** 台账 open 条数超阈值且新的手动 full 请求到达
- **THEN** 返回确认态要求二次确认，未确认不派发
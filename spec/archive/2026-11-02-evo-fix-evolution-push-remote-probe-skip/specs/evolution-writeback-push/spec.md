# spec：evolution-writeback-push

## ADDED Requirements

### Requirement: 零 remote 仓回写跳过 push

todo 回写与 daily self-review 的提交链路在执行 git push 前 SHALL 探测目标仓 remote 配置；无任何 remote 时 SHALL 跳过 push 并记 DEBUG 日志（含项目根路径），MUST NOT 产生 WARNING 级失败记录；提交语义不变。

#### Scenario: 零 remote 仓静默跳过

- **WHEN** 对无 remote 的项目仓执行回写提交
- **THEN** commit 照常产生，push 被跳过，日志级别为 DEBUG 且文案含项目根路径，无 WARNING

### Requirement: push 恒失败聚合告警

evolution todo 回写车道（self_review 车道每日至多一次 push，无刷屏面，不聚合）同一项目仓 push 连续失败时 SHALL 收敛为同日至多一条聚合告警，告警文案 SHALL 包含项目根路径与连续失败计数；当日后续失败 SHALL 仅递增计数并降级记 DEBUG，MUST NOT 新增常规 WARNING。

#### Scenario: 连续失败不刷屏

- **WHEN** 同仓 push 连续第 2 次及以上失败且当日已发过聚合告警
- **THEN** 仅递增失败计数并降级记 DEBUG，不新增聚合告警、也不记常规 WARNING（同仓同日 WARNING 至多一条）；跨日重置的是当日已告警标记（连续失败计数自最近一次成功 push 起累计、成功清零），次日首败再发含最新计数的一条聚合

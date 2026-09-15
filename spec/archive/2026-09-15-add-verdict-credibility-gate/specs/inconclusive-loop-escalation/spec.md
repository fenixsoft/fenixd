# spec: inconclusive-loop-escalation（inconclusive 循环升级）

## ADDED Requirements

### Requirement: 连续 blocked-env 达阈值时呼叫 Administrator

`_handle_env_blocked_inconclusive` 的连续计数达到升级阈值（`verify_engine.inconclusive_escalate_attempts`，默认 4）时，必须向 admin store 写入待唤起 SIGNAL 记录，由 admin_monitor 摄取后唤起 Administrator——不依赖 stuck/blocked_stuck/repeated_failures 任一既有检测规则（三层口径均已实证错过该故障形态）。

#### Scenario: 第 4 轮全批 blocked-env 触发 SIGNAL 写入

- **WHEN** 连续第 4 轮验证全部场景为 blocked-env（`_inconclusive_attempts` 达到 4，含暂停分支触发时刻）
- **THEN** 向 admin store 写入 kind=SIGNAL 记录（type=`inconclusive_loop`，含 spec 名、连续轮数、末轮 blocked_env 数、最近实例端口/探针摘要）
- **AND** admin_monitor 摄取该记录后按既有 SIGNAL 通道唤起 Administrator（family_explosion/dispatch_stalled 同款路径）

#### Scenario: 阈值内不提前唤起

- **WHEN** 连续轮数为 1-3（重验与暂停的正常区间）
- **THEN** 不写入 SIGNAL（维持既有自动重验→暂停语义，不产生噪音告警）

#### Scenario: 处置建议指向环境核查

- **WHEN** Administrator 因 inconclusive_loop 信号被唤起
- **THEN** 处置建议包含：验证环境核查清单（实例就绪/资源与并行度/mock+SSE 链路/探针摘要）与恢复路径（人工处置后解冻并清 `_inconclusive_attempts`）

#### Scenario: 人工处置后计数清零恢复正常调度

- **WHEN** 人工清 `_inconclusive_attempts` 并使 spec 回到可调度态
- **THEN** 后续 blocked-env 轮次从 1 重新计数，不再残留旧计数（与 unfreeze 清 verify_redo_count 同语义）

#### Scenario: 阈值可配置

- **WHEN** 配置 `verify_engine.inconclusive_escalate_attempts` 为其他正整数 N
- **THEN** 第 N 轮全批 blocked-env 时触发 SIGNAL 写入（缺省 4）

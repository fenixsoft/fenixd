# spec-merge-circuit-breaker

## MODIFIED Requirements

### Requirement: Merge 失败指纹熔断
Fenixd SHALL 对 implementer merge-back 失败计算稳定失败指纹（对错误信息做归一化哈希）。同一 spec 的同一指纹连续失败达到阈值（默认 2 次）后，Fenixd MUST 将 spec 置为 `blocked` 状态并停止自动重试，等待人工介入。人工确认根因消除并将状态重置为 `ready` 后，Fenixd SHALL 恢复对该 spec 的正常调度。repair 通道（mergeback-inplace-repair）轮次不重置连续计数：repair 失败后 fallback 重派引发的 merge-back 失败与前序失败连续累计；spec 进入 blocked 后 repair 通道一并停止，不再派发 repair agent。

#### Scenario: 连续两次相同 merge 失败进入 blocked
- **WHEN** 某 spec 的 implementer merge-back 因「本地改动将被覆盖」失败，指纹为 F
- **AND** 重试后再次以相同指纹 F 失败
- **THEN** spec 状态变为 `blocked`，错误信息记录指纹 F，且不再自动派发 implementer

#### Scenario: 不同指纹失败不触发熔断
- **WHEN** 某 spec merge-back 首次以指纹 F1 失败，重试后以不同指纹 F2 失败
- **THEN** spec 按现有重试逻辑处理（`_retry_count` 递增），不进入 blocked

#### Scenario: blocked 状态可人工恢复
- **WHEN** spec 处于 blocked 状态，人工将状态改为 ready
- **THEN** Fenixd 恢复对该 spec 的正常调度

#### Scenario: repair 中插轮不重置计数
- **WHEN** merge-back 以指纹 F 失败 → repair 1 轮完成并 re-merge-back → 仍以指纹 F 失败
- **THEN** 按连续 2 次相同指纹进入 blocked，repair 轮不重置连续计数

#### Scenario: blocked 后 repair 一并停止
- **WHEN** spec 因 merge 失败熔断进入 blocked，且实现分支仍存活
- **THEN** 不派发 repair agent，等待人工介入

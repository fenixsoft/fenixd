# Spec Delta: post-recovery-patrol

## MODIFIED Requirements

### Requirement: 每次自动恢复后必须安排闭环复查

任何 auto-recovery 动作（状态重置、跟踪清理）完成后，系统 MUST 登记一个观察项，在 `pm.recovery.followup_check_minutes` 后复查该 spec 是否已真实恢复推进（已被派发或进入后续状态）；复查未通过 MUST 触发 Administrator 信号。

复查的「已真实恢复推进」判据 MUST 以本条声明的**语义**为准，而不是「status 与登记时是否相同」：观察窗口到达时，若该 spec 处于 `ready` 且无活跃派发，无论其 status 是否与登记时不同（典型形态：登记时为 implementing，窗口内因中断回退为 ready），均 MUST 判为**尚未恢复推进**。

判为尚未恢复推进时，系统 MUST 先尝试**就地重新派发**该 spec（走与 `spec_ready` 事件同源的派发路径，经既有依赖/预算/内容完整性/冻结闸门）。派发成立时 MUST 关闭观察项且不产生任何告警；派发未成立时 MUST 关闭观察项并以 `dispatch_stalled` 信号唤起 Administrator 处置。

#### Scenario: 复查发现仍卡在假就绪

- **WHEN** 观察窗口到达时该 spec 仍为 ready、窗口内没有任何成功的实现派发记录，且就地重新派发未成立
- **THEN** 系统 MUST 以 dispatch_stalled 信号唤起 Administrator 处置，并在处置结果中可追溯到当初的恢复动作

#### Scenario: 复查确认已恢复推进

- **WHEN** 观察窗口到达时该 spec 已进入 ready 之后的后续状态（implemented / testing / verified / done / pushed）或已有活跃派发
- **THEN** 系统 MUST 关闭观察项且不产生任何告警

#### Scenario: 窗口内回退到 ready 的观察项以就地派发收口

- **WHEN** 观察项登记时该 spec 为 implementing，窗口内因中断回退为 ready 且无活跃派发
- **THEN** 系统 MUST 判为尚未恢复推进、就地重新派发该 spec，并在派发成立后关闭观察项、不产生任何告警

#### Scenario: 就地派发受闸门拦截时不静默关闭

- **WHEN** 观察窗口到达、spec 滞留 ready 且就地重新派发被预算闸门或内容完整性闸门拦下
- **THEN** 系统 MUST 关闭观察项并发出 dispatch_stalled 信号，MUST NOT 仅记日志静默关闭

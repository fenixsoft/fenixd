# Spec Delta: post-recovery-patrol

## ADDED Requirements

### Requirement: 每次自动恢复后必须安排闭环复查
任何 auto-recovery 动作（状态重置、跟踪清理）完成后，系统 MUST 登记一个观察项，在 `pm.recovery.followup_check_minutes` 后复查该 spec 是否已真实恢复推进（已被派发或进入后续状态）；复查未通过 MUST 触发 Administrator 信号。

#### Scenario: 复查发现仍卡在假就绪
- **WHEN** 观察窗口到达时该 spec 仍为 ready 且窗口内没有任何成功的 implementer 派发记录
- **THEN** 系统 MUST 以 dispatch_stalled 信号唤起 Administrator 处置，并在处置结果中可追溯到当初的恢复动作

#### Scenario: 复查确认已恢复推进
- **WHEN** 观察窗口到达时该 spec 已离开 ready 或已有活跃派发
- **THEN** 系统 MUST 关闭观察项且不产生任何告警

### Requirement: 巡检范围覆盖假就绪态
周期巡检与 BLOCKER CHECK MUST 检查非运行态 spec 的滞留情况：某 spec 停留 ready 超过 `pm.recovery.ready_stall_threshold_minutes` 且期间无成功派发时 MUST 被报告为阻塞项；「无 in-progress SPEC」MUST NOT 成为跳过整轮巡检的理由。

#### Scenario: 无 in-progress 但有假 ready 滞留
- **WHEN** 巡检运行时所有 spec 都不在 implementing/testing 等运行态，但存在一个 ready 滞留超阈值的 spec
- **THEN** 系统 MUST 报告该滞留并继续巡检其余检查项，不得因「No in-progress SPECs」提前返回

### Requirement: 同类告警按指纹限频防止重复拉起
对同一 spec 的 dispatch_stalled 类信号 MUST 使用指纹去重：指纹未变化且处于冷却期内时，系统 MUST 记录事件但不得重复拉起 Administrator。

#### Scenario: 冷却期内重复检测到同一滞留
- **WHEN** 某假就绪滞留在冷却窗口内被多轮巡检反复检出且状态指纹无变化
- **THEN** 仅首次触发拉起 Administrator，后续轮次只追加日志；指纹变化或冷却期结束方可再次拉起

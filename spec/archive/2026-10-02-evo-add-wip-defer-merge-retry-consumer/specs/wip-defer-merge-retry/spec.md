# wip-defer-merge-retry 规格

## ADDED Requirements

### Requirement: WIP 阻断落结构化载体

spec 车道合回被 WIP 重叠闸门阻断时，系统 SHALL 在 spec 状态上落结构化等待标志（含重试计数与首阻时刻）并持久化往返，SHALL NOT 以 error 文本作为唯一现场标志。

### Requirement: 周期消费者自动合回

daemon 运行期 SHALL 周期复查带等待标志的 spec：主树重叠文件已干净时，SHALL 在主树锁内执行 merge-only 重试并走既有成功收尾（implemented 推进、标志清账、mergeback_wip_overlap 告警显式闭环）；重试 SHALL 有状态守卫——仅 implementing 且带标志的条目可重试，已推进条目跳过并清账。

### Requirement: 有界与降级

自动重试 SHALL 设窗口与轮数上限（对齐 code-fix defer 的 90 分钟/6 次范式）；超限 SHALL 停止自动重试并降级为人工处置告警。

### Requirement: 先于孤儿探测生效

周期消费者 SHALL 先于 orphaned_state 探测触发（节拍短于其缺省 15 分钟阈值），使「WIP 清了自动合回」成为默认路径、admin 仅处理真冲突与超限降级。等待期内（未超窗口/轮数上限）orphaned_state 探测 SHALL 豁免带等待标志的条目；超限降级后豁免 SHALL 自动失效（孤儿探测恢复兜底）。

#### Scenario: WIP 清理后自动合回

- WHEN 带等待标志的 spec 在周期复查时主树重叠文件已干净
- THEN 自动 merge-only 重试成功、spec 推进 implemented、标志清账、原 major 告警闭环

#### Scenario: 人工已处置不重复合并

- WHEN 重试触发时 spec 已非 implementing（人工/admin 已合并推进）
- THEN 跳过重试并清账，不产生非法状态转移或重复合并

#### Scenario: WIP 长期不清理降级

- WHEN 等待超过窗口或重试超过轮数上限
- THEN 停止自动重试、降级为人工处置告警并保留现场标志

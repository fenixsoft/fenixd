# admin-orphan-disposition-effect-check 规格

## ADDED Requirements

### Requirement: 孤儿处置收敛前核查动作实际生效
AdminMonitor 的孤儿处置扫描 SHALL 对「final 处置组 ∧ 关联底层 SIGNAL 记录仍未收口（unhandled_signal_for 命中，escalated=true 口径；SIGNAL 记录 spec=null 与 DISPOSITION 记录 spec="global" 的记法差异 SHALL 归一化匹配）」的处置组做只读生效核查（依据 STATE 的 frozen/status 与 fenixd.log Transition 留痕等真实状态证据，组 spec 为 global/None 时以日志时间窗对账为准；SHALL NOT 仅以处置记录文本自证）。组内已有 escalate=true 终结记录或同 spec 存在在飞 admin run 时 SHALL 跳过。核查确认动作已生效时，SHALL append 一条注明补记与依据的 resolved 处置记录，并对关联信号执行 mark_signal_handled 收口。

#### Scenario: 解冻动作已实际生效
- **WHEN** 某处置组已 final（含 partially-resolved 终态与滞留 pending 占位）且其关联底层 SIGNAL（spec=null 形态归一化匹配）仍未收口，而其目标动作已在真实状态生效（目标 spec 在 STATE 中已解冻并推进、日志有 Transition 留痕）
- **THEN** 扫描不再永久跳过该组，append 注明补记的 resolved 处置记录，关联信号转 handled

#### Scenario: 动作未实际生效
- **WHEN** 生效核查未找到真实状态证据（spec 仍 frozen 或状态未推进）
- **THEN** 不补记 resolved，该组维持滞留并走既有孤儿升级路径（fail-closed）

#### Scenario: 已升级或在飞组不重复收敛
- **WHEN** 组内已有 escalate=true 终结记录，或同 spec 存在在飞 admin run
- **THEN** 不补记、不收口，维持既有升级/在飞语义

#### Scenario: 生效核查不看记录自证
- **WHEN** 处置记录 summary 声称动作已计划或已执行
- **THEN** 收敛决策只依据 STATE/日志等外部真实状态证据，不采信处置记录文本本身

### Requirement: 结构化 choice 通道小步落账
AdminMonitor 结构化 choice 通道 SHALL 在单个处置动作执行成功后立即落一条逐动作 DISPOSITION 事件（含 action_taken 与结果；事件 SHALL NOT 携带 admin_run_id，SHALL NOT 使 _merge_admin_runs 判定组提前 final）；choice 整体执行成功时可提前执行信号收口；choice 任一步骤失败 SHALL NOT 提前收口、SHALL NOT 预写 resolved。

#### Scenario: 动作成功即落账
- **WHEN** 结构化通道中某 choice 动作执行成功而 run 后续步骤尚未完成
- **THEN** 该动作的处置事件已在落账时点持久化且不携带 admin_run_id（不破坏该 run 的在飞判据），run 进程死亡不丢失已执行事实

#### Scenario: 部分失败不提前收口
- **WHEN** 某 choice 的多步动作中部分步骤失败（choice 整体非 ok）
- **THEN** 不出现提前的信号收口，也不出现 result=resolved 的预写记录（维持 fail-closed）

#### Scenario: 动作失败不预写
- **WHEN** 某 choice 动作执行失败
- **THEN** 不出现 result=resolved 的预写记录（维持 evo-fix-global-signal-choice-execution 的 fail-closed 语义）

### Requirement: 补记不破坏既有记录
补记 SHALL 以 append 新记录方式落账，SHALL NOT 就地改写既有 pending 或终态记录；孤儿扫描的 final 归并语义 SHALL 保持兼容（append 非 pending 记录不得引发重复收敛死循环）。

#### Scenario: 补记后幂等
- **WHEN** 同一处置组已被补记 resolved 并收口
- **THEN** 后续扫描轮次不再重复补记或重复收口
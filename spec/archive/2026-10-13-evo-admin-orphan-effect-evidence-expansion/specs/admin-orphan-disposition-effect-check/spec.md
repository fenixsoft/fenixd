# admin-orphan-disposition-effect-check 规格（delta）

## MODIFIED Requirements

### Requirement: 孤儿处置收敛前核查动作实际生效
AdminMonitor 的孤儿处置扫描 SHALL 对「final 处置组 ∧ 关联底层 SIGNAL 记录仍未收口（unhandled_signal_for 命中，escalated=true 口径；SIGNAL 记录 spec=null 与 DISPOSITION 记录 spec="global" 的记法差异 SHALL 归一化匹配）」的处置组做只读生效核查。组内已有 escalate=true 终结记录或同 spec 存在在飞 admin run 时 SHALL 跳过（既有守卫②/⑤语义不变；已升级组不因本能力新增证据家族而恢复复查，存量已升级组仍走人工 resolve 收口）。核查确认动作已生效时，SHALL append 一条注明补记与依据的 resolved 处置记录，并对关联信号执行 mark_signal_handled 收口；SHALL NOT 仅以处置记录文本自证。

「处置已生效」的证据来源 SHALL 为按处置动作类型的证据家族并集，任一家族命中即判定生效；全部家族未命中时维持 fail-closed 升级（不新增自动豁免）：

1. 解冻留痕（既有家族，扩展检索面）：日志检索文件集为 fenixd.log 与 fenixd.log.1.._LOG_ROTATION_BACKUPS（core/admin_monitor.py:166 常量，回退写法参照 :3451 既有实现），按对账窗口 [组内最早 created-_ORPHAN_EFFECT_LOG_SLACK_SECONDS, now] 只消费时间戳落在窗内的行；mtime 早于窗口起点的文件跳过，单文件读取仍限尾部容量（_TAIL_ERROR_READ_BYTES 语义不变），匹配 blocked→X 且 channel∈{manual,recovery} 的 Transition 留痕。
2. 提交类旁证（新增）：对账窗口内的 git log 中存在下列其一——(a) merge commit：`git log --merges` 窗口内提交且提交消息含目标 spec 名（合并目标分支名）；(b) 归档收尾提交：非 merge 提交且提交消息同时含目标 spec 名与归档收尾家族前缀。两类均须提交时间落在对账窗内；非 merge 提交仅满足单一消息条件的不命中（防假阳性）。
3. STATE 旁证（新增，仅限 global/None 组）：组 spec 为占位 "global"（core/admin_monitor.py:652 归一）时，SHALL 先从组内记录 actions_taken/evidence 或关联 SIGNAL 记录提取明确 spec 名 token（提取不到不猜测，跳过本家族），再回退 core/state_machine.read_one（:893）按与具体 spec 组同门判据（frozen=False 且 status 离开 blocked）核查；SPEC 读取失败或无条目时按无证据处理（fail-closed）。

机制 docstring 的「禁止记录自证」约束继续适用：新增证据家族同样只读外部痕迹（日志/git/STATE），处置记录文本仅可作提取 spec 名与建立对账窗口的指针，不构成生效证据本身。

#### Scenario: 解冻留痕在轮转文件中
- **WHEN** 某未升级 global 组的解冻 Transition 留痕已轮转出 fenixd.log 尾部、落在 fenixd.log.1..N 候选集内且时间戳落在对账窗口内
- **THEN** 解冻留痕家族命中，append 补记 resolved 并收口关联信号，不再升级

#### Scenario: 治愈动作为提交或合并
- **WHEN** 某未升级组的治愈动作是对账窗口内的分支 merge commit，或提交消息同时含目标 spec 名与归档收尾家族前缀的收尾提交
- **THEN** 提交类家族命中并收口，不再升级

#### Scenario: STATE 旁证可提取与不可提取
- **WHEN** global 组记录中可提取明确 spec 名，且该 spec 在 STATE 中 frozen=False 且 status 离开 blocked
- **THEN** STATE 家族命中并收口
- **WHEN** 提取不到明确 spec 名，或提取到的 spec 在 STATE 无条目/读取失败
- **THEN** 跳过 STATE 家族继续尝试其余家族，不猜测、不假闭环

#### Scenario: 全部家族未命中维持 fail-closed
- **WHEN** 三类证据家族在对账窗口内均无命中
- **THEN** 行为与现状一致：不补记，维持滞留并走既有升级路径

#### Scenario: 提交消息假阳性不误判
- **WHEN** 窗口内非 merge 提交的消息仅含 spec 名或仅含家族前缀（未同时满足），或窗口内 merge commit 消息不含目标 spec 名，或提交时间落在窗口外
- **THEN** 提交类家族不命中，不据此收口

#### Scenario: 已升级或在飞组不重复收敛
- **WHEN** 组内已有 escalate=true 终结记录，或同 spec 存在在飞 admin run
- **THEN** 不补记、不收口，维持既有升级/在飞语义（已升级组不因新增证据家族恢复自动收口）

#### Scenario: 生效核查不看记录自证
- **WHEN** 处置记录 summary 声称动作已计划或已执行
- **THEN** 收敛决策只依据 STATE/日志/git 等外部真实状态证据，处置记录文本仅作 spec 名提取与窗口建立之用

# 孤儿处置生效核查收敛

<!-- knowledge: capability=admin-orphan-disposition-effect-check rev=1
     sources=spec/archive/2026-10-11-evo-add-admin-orphan-disposition-effect-check -->

admin run 在「动作已执行、终态未落账」窗口死亡后，AdminMonitor 孤儿处置扫描对滞留处置组做只读生效核查，核查通过则 append 补记 resolved 并收口关联信号，使台账与真实状态对齐；结构化 choice 通道同时以逐动作小步落账缩短失账窗口。

## 规则

- 滞留判据唯一锚定「关联底层 SIGNAL 记录仍未收口」（`unhandled_signal_for` 命中，escalated=true 口径）。处置记录自身的 handled 字段无 mutator（恒为 false）、健康组的 pending 占位同样长期在场，二者均不可作滞留判据。
- SIGNAL 记录 spec=null 与 DISPOSITION 记录 spec="global" 的记法差异须归一化匹配（None ↔ "global"），不做归一化则全局形态永不命中。
- final 处置组不被孤儿扫描无条件跳过：final 组 ∧ 关联 SIGNAL 未收口即进入生效核查；组内已有 escalate=true 终结记录、或同 spec 存在在飞 admin run 时跳过（升级人工/在飞语义优先，不补记、不收口）。
- 生效核查只读、只信外部真实状态证据：目标 spec 在 STATE.md 的 frozen 标记与 status 推进、fenixd.log 的 Transition 留痕（channel/note 可与处置记录对账）；组 spec 为 global/None 时以处置记录 created 邻域时间窗内的日志迁移对账（如 blocked → 其他、channel=manual、note 与动作语义一致）。处置记录 summary 文本不得自证。
- 核查通过：append 一条注明补记（backfill）与依据的 resolved 处置记录，并对关联信号执行 mark_signal_handled 收口。
- 核查不通过（证据不足）：不补记 resolved，维持滞留并走既有孤儿升级路径（fail-closed——宁可滞留升级，不可假闭环）。

## 关键行为

- 结构化 choice 通道内单个处置动作执行成功后即落一条逐动作 DISPOSITION 事件（含 action_taken 与结果），run 进程死亡不丢已执行事实；choice 整体执行成功时可提前执行信号收口。
- 逐动作事件不携带 admin_run_id：不并入 `_merge_admin_runs` 组归并、不使组提前 final，维持「在飞 = has_pending 且非 final」判据与 `_spec_has_active_admin_run` 的重派/节流护栏。
- 信号提前收口以 choice 整体执行 ok 为准（`_apply_choice_execution` 返回 ok=True 才 mark_signal_handled），单动作成功不收口；choice 任一步骤失败不提前收口、不预写 resolved。
- 补记一律 append 新记录，不就地改写既有 pending 或终态记录；组内已存在 backfill 记录即跳过，后续扫描轮次不重复补记/收口（幂等，无重复收敛死循环）。
- 人工 dashboard 通道动作与收口原子，不经本收敛分支。

## 溯源

- 2026-10-11 evo-add-admin-orphan-disposition-effect-check（spec/archive/2026-10-11-evo-add-admin-orphan-disposition-effect-check） — 新建本页：孤儿处置生效核查补记收敛（final 组滞留锚定未收口信号、外部真实状态证据核查、append 补记幂等、升级/在飞豁免）与结构化通道逐动作小步落账（事件不携 run_id、choice 整体 ok 才收口）

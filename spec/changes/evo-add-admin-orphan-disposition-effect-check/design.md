# add-admin-orphan-disposition-effect-check 设计

## Context

admin 处置台账的生命周期：唤起前占位（maintenance_runs.py:274-291，pending）→ run 内动作执行（本例为 admin agent Bash 直调 execute_adjudication_choice，admin_actions.py:2312，不留痕）→ run 结束后 AdminMonitor._worker 统一落终态（admin_monitor.py:4367-4401）→ 回写门（:4425-4444，success 才 mark_signal_handled）。孤儿升级 _recover_orphaned_dispositions（:3813，grace 15 分钟）在 :3847-3849 对 _merge_admin_runs（:661-699）判定的 final 组直接 continue——崩溃在动作后、落账前的 run 留下「partial 终态 + handled=False + pending 占位」组合，扫描永久跳过，且无任何事后消费者（alert_lifecycle.py:66-71 只覆盖 4 类 escalation 信号）。

判别锚点取证（2026-10-05 复核 .fenix/admin_alerts.json）：DISPOSITION 记录的 handled 字段**无任何 mutator**（mark_handled 只匹配 ESCALATION，mark_signal_handled 只作用于 SIGNAL 记录），实测全部 38 条 disposition 记录 handled 恒为 false；且健康组的 pending 占位同样永久滞留（结构化通道终态 append 不改写占位，「pending+resolved」是常态组形）。故 disposition 自身的 handled 与组内滞留 pending 都不能当「滞留」判据——唯一可锚定的是**关联底层 SIGNAL 记录仍未收口**（unhandled_signal_for，escalated=true 口径）：429 现场信号 f63d10d2135b（handled=false、escalated=true）在账可锚定。注意 SIGNAL 记录 spec=null 而 DISPOSITION 记录 spec="global"，unhandled_signal_for 的 spec 严格相等匹配须做 None↔"global" 归一化，否则对本例形态永不命中。人工 dashboard 通道（alert_routes.py:466-505）动作与收口原子，不受影响。

## Goals / Non-Goals

- Goals：final-unhandled/滞留 pending 处置组被收敛（核查生效→补记→收口信号）；结构化通道窗口缩小。
- Non-Goals：不拦截 admin agent 的 Bash 直调通道（框架无法在动作时刻感知，只能靠收敛侧兜底）；不改回写门 fail-closed；不做处置记录的就地改写。

## Decisions

### D1：收敛侧是主承力点
本例真实通道是 Bash 直调（choice_id=null），「choice 粒度小步落账」对这类形态零作用；结构化通道内 execute（:4344）到 append（:4367）仅秒级窗口。因此 R1（孤儿收敛核查补记）为主，R2（小步落账）为廉价加固。

### D2：生效核查的证据源
只读核查看真实状态：目标 spec 在 STATE.md 的 frozen 标记与 status 推进（解冻类动作 → frozen=False 且 status 离开 blocked）、fenixd.log 的 Transition 留痕（channel/note 可与处置记录对账）。组 spec 为 global/None（无对应 SPEC 状态可读，如 429 现场）时以日志对账为主：在处置记录 created 邻域时间窗内检索解冻族迁移（blocked → 其他）且 channel/note 与动作语义一致（如 retry_review 的「重派评审」留痕）——2026-10-03T19:40:21 四条「blocked → reviewing / channel=manual / note=重派评审（人工裁决）」留痕在案，该配法对本例形态可判定。严禁以处置记录自身文本自证——那是 2026-10-04#失误#1（失败误记 resolved）的镜像风险。证据不足时维持滞留并走既有升级，绝不强行补 resolved。

### D3：补记形态复用预探写回先例
参照 _close_signal_preprobed（admin_monitor.py:2453-2496）：append 新记录（注明「补记」+依据）而非就地改写；DISPOSITION 记录无就地 mutator（admin_store.py:569-583 的 mark_handled 只匹配 ESCALATION），补记走 AdminStore.append 新增 result=resolved（note 注明 backfill）事件即可，_merge_admin_runs 的 final 归并语义无需改动且天然兼容。幂等靠「组内已存在 backfill 记录即跳过」判据。

### D4：小步落账的位置
_worker 内 _apply_choice_execution（:4344）成功返回后、final append（:4367）前，逐动作 append DISPOSITION 事件；信号收口仍按回写门语义（成功路径可提前 mark_signal_handled(action_taken, result=resolved)，签名已支持，admin_store.py:584）。失败路径不预写（红线，保 2.2 fail-closed）。两条硬约束：①逐动作事件 MUST NOT 携带 admin_run_id（循 _close_signal_preprobed 无 run_id 留痕先例）——携带会被 _merge_admin_runs 并入本组使组提前 final，破坏「在飞 = has_pending 且非 final」判据（_spec_has_active_admin_run 的重派/节流护栏失守）；②提前收口以 choice 整体执行 ok 为准（_apply_choice_execution 返回 ok=True 即 mark_signal_handled），不得按单动作成功收口——多步 choice 部分步骤失败时提前收口违背 2.2「信号保留待重审」。

## Risks / Trade-offs

- 生效核查误判「已生效」：以多源证据（STATE+日志）交叉降低风险；证据不足默认不补记（宁可滞留升级，不可假闭环）。
- 补记风暴：幂等判据（backfill 记录在场即跳过）+ 扫描周期天然节流。
- 误把健康组当滞留：判别锚点只用「关联 SIGNAL 未收口」——健康组（信号已 handled）与信号已归档的老年组天然不触发（实测 disposition.handled 恒 false、pending 占位健康组同样滞留，二者均不可作判据）。
- 收敛分支与在飞 run 竞态：final 组的关联信号可能已重派给在飞新 run——补记/收口前以 _spec_has_active_admin_run(spec, exclude_run_id=本组 rid) 排除在飞；组内已有 escalate=true 终结记录的组直接跳过（升级人工是唯一出路，与回写门 escalate 豁免同口径）。

## Migration Plan

单 commit 落地收敛分支 + 小步落账 + 测试；存量滞留记录（827b4f2fe0c8/613d42266fdb）由新收敛逻辑在下一扫描周期自然消费，无需手工清洗。

## Open Questions

- 无。
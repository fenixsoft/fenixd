# add-admin-orphan-disposition-effect-check 设计

## Context

admin 处置台账的生命周期：唤起前占位（maintenance_runs.py:274-291，pending）→ run 内动作执行（本例为 admin agent Bash 直调 execute_adjudication_choice，admin_actions.py:2312，不留痕）→ run 结束后 AdminMonitor._worker 统一落终态（admin_monitor.py:4367-4401）→ 回写门（:4425-4444，success 才 mark_signal_handled）。孤儿升级 _recover_orphaned_dispositions（:3813，grace 15 分钟）在 :3847-3849 对 _merge_admin_runs（:661-699）判定的 final 组直接 continue——崩溃在动作后、落账前的 run 留下「partial 终态 + handled=False + pending 占位」组合，扫描永久跳过，且无任何事后消费者（alert_lifecycle.py:66-71 只覆盖 4 类 escalation 信号）。人工 dashboard 通道（alert_routes.py:466-505）动作与收口原子，不受影响。

## Goals / Non-Goals

- Goals：final-unhandled/滞留 pending 处置组被收敛（核查生效→补记→收口信号）；结构化通道窗口缩小。
- Non-Goals：不拦截 admin agent 的 Bash 直调通道（框架无法在动作时刻感知，只能靠收敛侧兜底）；不改回写门 fail-closed；不做处置记录的就地改写。

## Decisions

### D1：收敛侧是主承力点
本例真实通道是 Bash 直调（choice_id=null），「choice 粒度小步落账」对这类形态零作用；结构化通道内 execute（:4344）到 append（:4367）仅秒级窗口。因此 R1（孤儿收敛核查补记）为主，R2（小步落账）为廉价加固。

### D2：生效核查的证据源
只读核查看真实状态：目标 spec 在 STATE.md 的 frozen 标记与 status 推进（解冻类动作 → frozen=False 且 status 离开 blocked）、fenixd.log 的 Transition 留痕（channel/note 可与处置记录对账）。严禁以处置记录自身文本自证——那是 2026-10-04#失误#1（失败误记 resolved）的镜像风险。证据不足时维持滞留并走既有升级，绝不强行补 resolved。

### D3：补记形态复用预探写回先例
参照 _close_signal_preprobed（admin_monitor.py:2453-2496）：append 新记录（注明「补记」+依据）而非就地改写；DISPOSITION 记录无就地 mutator（admin_store.py:569-583 的 mark_handled 只匹配 ESCALATION），补记走 AdminStore.append 新增 result=resolved（note 注明 backfill）事件即可，_merge_admin_runs 的 final 归并语义无需改动且天然兼容。幂等靠「组内已存在 backfill 记录即跳过」判据。

### D4：小步落账的位置
_worker 内 _apply_choice_execution（:4344）成功返回后、final append（:4367）前，逐动作 append DISPOSITION 事件；信号收口仍按回写门语义（成功路径可提前 mark_signal_handled(action_taken, result=resolved)，签名已支持，admin_store.py:584）。失败路径不预写（红线，保 2.2 fail-closed）。

## Risks / Trade-offs

- 生效核查误判「已生效」：以多源证据（STATE+日志）交叉降低风险；证据不足默认不补记（宁可滞留升级，不可假闭环）。
- 补记风暴：幂等判据（backfill 记录在场即跳过）+ 扫描周期天然节流。

## Migration Plan

单 commit 落地收敛分支 + 小步落账 + 测试；存量滞留记录（827b4f2fe0c8/613d42266fdb）由新收敛逻辑在下一扫描周期自然消费，无需手工清洗。

## Open Questions

- 无。
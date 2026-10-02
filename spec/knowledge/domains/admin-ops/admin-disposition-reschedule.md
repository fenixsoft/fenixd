<!-- knowledge: capability=admin-disposition-reschedule rev=1 sources=spec/archive/2026-09-23-evo-admin-disposition-reschedule -->

# 中断处置自动重派

AdminMonitor 孤儿处置检测对「known shutdown 中断的 admin run」的收尾策略：按底层信号未处理状态自动重派，超限升级人工。

## 现行规则

- 判定口径：known shutdown 中断指 run 转录含 interrupted 标记（`_run_has_interrupted_marker`）；底层信号指 admin_alerts.json 中 `kind=signal ∧ escalated=true ∧ handled=false` 的记录，匹配口径为 (signal_type, spec) 严格相等。
- 信号未处理时，孤儿检测不把中断 run 终结为 interrupted，而是调用 `_invoke_administrator` 重新入队新 admin run（新 admin_run_id，pending 记录由 `run_administrator` 自行落盘）。
- 重派入口直接复用 `_invoke_administrator`，不经 `_handle_signal`——否则冷却节流会把重派吞掉；signal 由 `_rebuild_dispatch_signal` 从信号记录重建。
- 重派有界：重派次数以 `reschedule_count` 计（落库在 DISPOSITION 记录，读取取该 (spec, signal_type) 族的最大值，缺省 0）；超限（默认 2）后不再自动重派，产生 `kind=escalation`、severity=critical 的人工告警（注明中断/重派次数），并为该 run 追加非 pending 终结 disposition（status=escalated）防每轮巡检重复升级。
- 幂等与并发安全：重派前以 `_has_active_admin_run_for(spec, signal_type)` 判定无在飞/待派发 run（同 (spec, signal_type) 存在 status=pending 的 disposition 记录，口径对齐 by_run 归并），避免双重派发。
- 审计留痕：原 pending disposition 追加 status=superseded 记录（同原 admin_run_id），actions_taken 注明 rescheduled from <原 run>，携带递增后的 reschedule_count；禁止为重派 run 追加 status=dispatched 的记录——同 admin_run_id 的非 pending 记录会使 by_run 归并把该 run 判为已终结，孤儿检测对其后续中断永久失效、计数上限永不生效。
- 底层信号已无未处理记录时，维持现状：终结为 interrupted，不重派。
- `escalated=true` 匹配口径的理由：仅在实际唤起 Administrator 时（节流通过）才落 escalated=true 的信号记录，节流分支落 escalated=False——以 escalated=true 匹配避免为从未唤起过的节流沉淀记录发起重派。

## 溯源

- 2026-09-23 evo-admin-disposition-reschedule（spec/archive/2026-09-23-evo-admin-disposition-reschedule） — 孤儿处置对已知中断从静默终结改为「查底层信号 → 重派或升级」，确立 reschedule_count 上限、superseded 留痕与禁写 dispatched 记录的约束

<!-- knowledge: capability=recovery-path-liveness rev=1 sources=spec/archive/2026-09-23-fix-recovery-path-blockers -->

# 恢复路径驱动证据与处置互斥

恢复链判定「SPEC 无驱动」与派发 verifier 时排除处置者自身的活动痕迹，并与在飞 Administrator 处置互斥，防止恢复路径被 admin run 文件挡住或与处置并行起跑。

## 现行规则

- 处置活动不计入驱动证据：`_has_recent_spec_run`（`core/admin_monitor.py` 模块级）与 `AdminMonitor._has_recent_progress`（同源实现）判定「某 SPEC 是否有近期写活动」时排除 `admin-` 前缀的 run 文件——Administrator 的处置 run 是处置者活动，不是被处置 SPEC 的验证/实现驱动证据；口径为「该 SPEC 是否存在非 admin 前缀、写活动在宽限窗内的 run 文件」。
- `spec_is_undriven` 与 `event_bus._recover_testing` 的无驱动条件按「真无驱动」语义判定：仅有 admin run 活动（如 `admin-<spec>-<ts>.jsonl` mtime 在宽限窗内，且无存活 agent 子进程、无待派发条目）时判为无驱动；存在 mtime 在窗内的 `impl-`/`verify-`/`repair-` 等非 admin 前缀 run 时判有驱动；admin run 文件超出宽限窗后判定结果与「无任何 run 文件」逐位一致。
- verifier 重验派发与在飞处置互斥：`event_bus._recover_testing` 与 admin_monitor 孤儿复位路径派发 verifier（`handle_event("spec_implemented", ...)`）前，检查该 SPEC 是否存在在飞或待派发的 Administrator run；存在则跳过本次重验派发并记 INFO/WARNING。判定走 `AdminMonitor._has_active_admin_run_for_spec(spec)`：复用既有 `_has_active_admin_run_for` 的 by_run 归并口径（某 `admin_run_id` 组 `has_pending` 且无终结兄弟记录）但去掉 signal_type 过滤，覆盖任意 signal_type（orphaned_state / verify_env_blocked / manual-intervention / stuck 等）——按 `(spec, signal_type)` 精确匹配会漏非 orphaned_state 处置；既有带 signal_type 的版本语义与调用点不变。
- 抑制重复唤起：`AdminMonitor._handle_signal` 在唤起前（`_invoke_administrator` 之前）检查该 SPEC 是否存在在飞 admin run，存在则跳过本次唤起并记 INFO/WARNING；信号仍按既有沉淀/节流语义落 store（不丢痕）——无此守卫时，处置中的 SPEC 会在 escalation 冷却窗过期后重新成条，产生与在飞处置并行的第二个 Administrator run。
- fail-open：admin 在飞判定本身异常（如 store 不可读）时按「无在飞 admin」放行并记 WARNING，不因守卫故障阻断恢复。
- 场景原地修复预算耗尽的显式重验日程：`_handle_scenario_repaired` 的预算耗尽分支（`_repair_depth >= _SCENARIO_REPAIR_MAX_ROUNDS`）按跨轮持久计数 `_scenario_repair_exhausted_rounds` 分两态——首次耗尽（计数 0）落显式、可观测的重验日程（排程定时重入 + `_dispatch_backoff_until` 兜底），SPEC 保持 testing、计数递增为 1，不升级人工、不原地重入；再次耗尽（计数 ≥1）走既有升级通道呼叫人工（保持 testing），不再排程。
- 首次/再次态判定在写 error 文案之前完成，首次态文案（含可读的下次重验时刻）不被「等待下一轮重验」文案覆盖。排程幂等：同一 SPEC 在同一耗尽态下重复进入该分支不排多个重验定时器（`_dispatch_backoff_until` 已生效即视为已排程）。
- 排程到期触发一次重验（等价 `_recover_testing` 的 `spec_implemented` 语义），该次重验重新获得完整的修复预算（`_repair_depth` 从 0 起算）；排程回调与 `_dispatch_backoff_until` 到期后的周期兜底两者皆可能触发，依赖既有 `_enqueue` 按 `(spec, agent_type)` 去重与 `_process_queue` 的 `_dispatch_backoffed` 门保证只起一次 verifier run。
- `_scenario_repair_exhausted_rounds` 与 `_judge_rerun_count` 同生命周期：仅在 `verified` 落定与人工 `unfreeze_spec` 两处清零；admin 处置复位（`transition_gate(testing)` 直通道或孤儿复位）不清零（生命周期累计语义）。

## 溯源

- [2026-09-23 fix-recovery-path-blockers](spec/archive/2026-09-23-fix-recovery-path-blockers/) — 新增驱动证据排除 admin 前缀、verifier 重验与在飞处置互斥（含重复唤起抑制与 fail-open）与场景修复预算耗尽的两态重验日程

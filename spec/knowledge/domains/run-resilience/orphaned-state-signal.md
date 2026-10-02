<!-- knowledge: capability=orphaned-state-signal rev=2 sources=spec/archive/2026-09-20-add-control-plane-silent-failure-guards,spec/archive/2026-10-02-evo-add-wip-defer-merge-retry-consumer -->

# 孤儿状态信号（状态无驱动探测）

巡检中分钟级发现「状态在 implementing/testing 却无任何驱动」的悬置 SPEC 并给出恢复出口，不必等 stuck 的 160 分钟长阈值。

## 现行规则

- 无驱动判定三条件同时成立才判 `orphaned_state`：① 无活动 run 文件——`.fenix/runs/` 下属于该 spec 的 run 文件 mtime 均超出宽限窗；② 无存活 agent 子进程——不存在 `impl-<spec>-` / `verify-<spec>-` 模式的存活进程；③ 无待派发——无针对该 spec 的待处理派发/恢复挂起（transient backoff 未到期、暂存待拾取、`_cancelled_hold`、start_after 定时未到等有意等待态均属「有意等待」）。任一条件不成立（长 run 仍在跑、进程仍存活、有意等待中）不得判无驱动。
- 持续时间阈值显著短于既有 stuck 阈值（`run_timeout_seconds + 600s` ≈ 160 分钟），缺省约 10–15 分钟；该阈值单源可配，与 stuck 阈值互不影响。
- 恢复出口：信号经既有 Administrator 通道唤起处置；处置完成后走既有复位直通道——分支已合并则 `transition_gate(testing)` + verifier 入队重验，否则回 `ready`。`core/event_bus.py` 运行期恢复（`_recover_one`）对 testing 且无活动 run/进程的 spec 不静默留白（补恢复动作或联动 `orphaned_state`）；implementing 态既有 recovery 分支语义保持不变，运行期悬置无需等 daemon 重启即被发现并重派。
- 等待期豁免：`_wip_gate_deferred=True` 且未超限（重试计数 < 6 且等待窗口 < 90 分钟，判据与消费侧同一常量口径）的 implementing 悬置条目跳过孤儿探测——该条目由 WIP 延迟合回周期消费者驱动（见 [WIP 阻断延迟合回](../worktree-vc/wip-defer-merge-retry.md)）；超限降级后豁免自动失效，探测恢复兜底。
- 信号登记与去重：`SIGNAL_SEVERITY` 登记 `orphaned_state`、`SIGNAL_RECOMMENDATION` 登记处置指引；同一 spec 同类信号走既有 `escalation_cooldown_minutes` 节流，冷却窗内连续多轮巡检命中只唤起一次 Administrator。

## 溯源

- 史前复原 — 迁移期基线：孤儿状态经事件补发、周期扫描与白名单恢复收敛；孤儿恢复对 error 的清空必须持久化，不得只改内存
- 2026-09-20 add-control-plane-silent-failure-guards（spec/archive/2026-09-20-add-control-plane-silent-failure-guards） — 确立 `orphaned_state` 三条件探测口径、独立于 stuck 的分钟级短阈值、testing 态运行期恢复出口与信号登记节流
- 2026-10-02 evo-add-wip-defer-merge-retry-consumer（spec/archive/2026-10-02-evo-add-wip-defer-merge-retry-consumer） — 新增等待期豁免：带 WIP 延迟合回标志且未超限的条目跳过孤儿探测，超限降级后豁免自动失效

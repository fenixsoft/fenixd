<!-- knowledge: capability=orphaned-state-signal rev=3 sources=spec/archive/2026-09-20-add-control-plane-silent-failure-guards,spec/archive/2026-10-02-evo-add-wip-defer-merge-retry-consumer,spec/archive/2026-10-08-evo-inprocess-verify-activity-signal -->

# 孤儿状态信号（状态无驱动探测）

巡检中分钟级发现「状态在 implementing/testing 却无任何驱动」的悬置 SPEC 并给出恢复出口，不必等 stuck 的 160 分钟长阈值。

## 现行规则

- 无驱动判定外置 run 形态条件须全部成立才判 `orphaned_state`：① 无活动 run 文件——`.fenix/runs/` 下属于该 spec 的 run 文件 mtime 均超出宽限窗；② 无存活 agent 子进程——不存在 `impl-<spec>-` / `verify-<spec>-` 模式的存活进程；③ 无待派发——无针对该 spec 的待处理派发/恢复挂起（transient backoff 未到期、暂存待拾取、`_cancelled_hold`、start_after 定时未到等有意等待态均属「有意等待」）。任一条件不成立（长 run 仍在跑、进程仍存活、有意等待中）不得判无驱动。
- 进程内验证活性信号（主判据）：全量验证以 daemon 进程内线程 `fenix-verifier-<spec>` 执行，无 run 文件、无独立子进程，上述外置形态条件对其不可见；判定因此并入进程内活性探测——`threading.enumerate()` 存在名为 `fenix-verifier-<spec>` 的活线程即判有驱动，零时间窗依赖（单场景长批静默 4-5 分钟不误判停滞）；线程名从派发队列命名单点（`agent_worker_thread_name`）取值，判定侧与派发侧禁各自硬编码字面量。
- 进度文件辅证 OR 臂：`.fenix/verify-progress/<spec>.json`（验证引擎起跑即写、逐场景原子刷新的既有进度产物）mtime 落入独立活动窗口（`INPROCESS_VERIFY_ACTIVITY_WINDOW_SECONDS`，缺省 900s、对齐孤儿阈值）亦判有驱动；该窗口显式独立于条件①的 120s run 宽限，两者互不复用；条件①的 120s 宽限本身保持不动。
- 口径边界：verifier 线程已退出且进度文件超独立窗时，判定结果与既有外置形态口径完全一致，无新增豁免；验证起跑即写进度文件，run 崩溃残留的新鲜 mtime 可短暂豁免孤儿判定，下一窗口超窗即自愈；线程臂无时间上界——挂死不退出的线程持续豁免，回收依赖验证车道既有超时与升级机制。
- 消费点同源豁免：周期孤儿探测与运行期恢复（`event_bus._recover_testing`）共用同一判定函数，进程内验证活跃期自动豁免，不再发 `orphaned_state` 也不重派验证；处置复位直通道（testing 分支 transition + 重派，不经判定函数）重派前以同一 helper 复核在飞验证，命中即跳过本次重派——`transition_gate(testing)` 幂等与清 error 的复位语义保留，不设延迟队列（处置复位单次消费无人回放触发，在飞验证本身即重验，其结果路径照常推进状态）。
- 持续时间阈值显著短于既有 stuck 阈值（`run_timeout_seconds + 600s` ≈ 160 分钟），缺省约 10–15 分钟；该阈值单源可配，与 stuck 阈值互不影响。
- 恢复出口：信号经既有 Administrator 通道唤起处置；处置完成后走复位直通道——分支已合并则 `transition_gate(testing)` + verifier 入队重验，否则回 `ready`。`core/event_bus.py` 运行期恢复（`_recover_one`）对 testing 且无活动 run/进程的 spec 不静默留白（补恢复动作或联动 `orphaned_state`）；implementing 态既有 recovery 分支语义保持不变，运行期悬置无需等 daemon 重启即被发现并重派。
- 等待期豁免：`_wip_gate_deferred=True` 且未超限（重试计数 < 6 且等待窗口 < 90 分钟，判据与消费侧同一常量口径）的 implementing 悬置条目跳过孤儿探测——该条目由 WIP 延迟合回周期消费者驱动（见 [WIP 阻断延迟合回](../worktree-vc/wip-defer-merge-retry.md)）；超限降级后豁免自动失效，探测恢复兜底。
- 信号登记与去重：`SIGNAL_SEVERITY` 登记 `orphaned_state`、`SIGNAL_RECOMMENDATION` 登记处置指引；同一 spec 同类信号走既有 `escalation_cooldown_minutes` 节流，冷却窗内连续多轮巡检命中只唤起一次 Administrator。

## 溯源

- 史前复原 — 迁移期基线：孤儿状态经事件补发、周期扫描与白名单恢复收敛；孤儿恢复对 error 的清空必须持久化，不得只改内存
- 2026-09-20 add-control-plane-silent-failure-guards（spec/archive/2026-09-20-add-control-plane-silent-failure-guards） — 确立 `orphaned_state` 三条件探测口径、独立于 stuck 的分钟级短阈值、testing 态运行期恢复出口与信号登记节流
- 2026-10-02 evo-add-wip-defer-merge-retry-consumer（spec/archive/2026-10-02-evo-add-wip-defer-merge-retry-consumer） — 新增等待期豁免：带 WIP 延迟合回标志且未超限的条目跳过孤儿探测，超限降级后豁免自动失效
- 2026-10-08 evo-inprocess-verify-activity-signal（spec/archive/2026-10-08-evo-inprocess-verify-activity-signal） — 判定并入进程内验证活性信号（spec 侧称条件⑤）：命名线程探测为主判据、进度文件独立窗口 mtime 为辅证；2026-10-02 cimbar-airgap-transfer 验证活跃期误判孤儿态致三批 23 场景交错重派的缺陷自此根治，处置复位直通道增加在飞复核

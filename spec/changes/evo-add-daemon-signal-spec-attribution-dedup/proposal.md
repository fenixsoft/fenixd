## Why

一次 merge-back 阻塞事件同时产生 spec 级信号（mergeback_wip_overlap）与 daemon 级同指纹升级信号（daemon_errors），派发器按信号 1:1 各派一个 administrator run：2026-10-10 13:37:29（本地）同秒双派 admin-pack2-live-stream-player-1791610649（412.8 秒/32 轮）与 admin-global-1791610649（449.9 秒/50 轮），前者零增量产出。第二实例已现：verify_env_blocked 升级（admin-pack2-live-stream-player-1791602498，3117 秒）与指纹 742cfaea 升级（admin-global-1791602544，3831 秒）间隔 46 秒双开、独立重复同一诊断链。代码层根因：在飞互斥守卫（core/admin_monitor.py:2834、:4269、:4523）以 spec 名为键，daemon 级信号 spec 为空时守卫短路失效；daemon run 的 spec 占位为 global，与 spec 级信号永不互见。既有 _make_daemon_error_signal_merged（core/admin_monitor.py:3964）只合并 daemon_errors 同轮多指纹；归档 fix-admin-cross-type-duplicate-dispatch（2026-10-07）只覆盖有 spec 键的跨类型互斥，daemon 级无 spec 信号在其外。

## What Changes

1. spec 归属提取：daemon 级信号（spec 为空）进入派发判定前，从 evidence 的 ERROR 原文提取 spec 归属——分支名（fenix/<spec>-<时间戳> 形态）正则与 spec 名直接匹配双线索，任一命中即归属。
2. 在飞互查扩展：提取到 spec 归属且该 spec 已有在飞 admin run 时跳过本次派发——信号保持未消费（不 mark handled），附「被在飞 run 覆盖、待重评」注记，在飞 run 终态后按既有再武装范式自然重评（core/admin_monitor.py:2826-2830 注释所述形态）。
3. 兜底不变：提取不到归属或归属 spec 无在飞 run 时，派发行为与现状完全一致。

## Out of Scope

- 不做「合并派发单个 run、回写多信号 disposition」的重结构（_invoke_administrator 的 signal_rec 单条绑定与 mark_signal_handled 回写路径不动）。
- 不加派发延迟缓冲窗口（不因聚合延迟 critical 信号处置）。
- 不改 _make_daemon_error_signal_merged 同轮多指纹合并语义与指纹升级阈值。
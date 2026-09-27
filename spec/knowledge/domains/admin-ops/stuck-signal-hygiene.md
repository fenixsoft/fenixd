<!-- knowledge: capability=stuck-signal-hygiene rev=1 sources=spec/archive/2026-09-21-evo-stuck-signal-hygiene -->

# stuck 信号活跃度预检与处置后静默

stuck 信号的误报降噪：进程存活反证优先于文件活跃判据、resolved 处置后设静默期、真 stuck 照常成条。

## 现行规则

- stuck 主判据不变：spec `updated` 时间超阈值仍是触发前提；预检与静默只做降噪，不替代主判据。
- 进程存活反证：stuck 判定前，若该 spec 存在登记在跑且进程存活的 run（`AgentRunner.running_run_ids()`，以进程表 `_running_agents` 为真相），判非 stuck、不产生信号——转录文件 mtime 停止增长不推翻进程存活事实。
- 进程存活但长时间无 token 产出的 hang 不判 stuck（接受该代价）：由 `agents.run_timeout_seconds` 超时终止兜底，超时后进程退出，下一轮巡检按「无存活进程」正常判 stuck。
- 记录层去重由 `merge_signal` 状态沉淀承担：冷却窗口内同 `(spec, signal_type, status_hash)` 重复触发不新增 signal 记录、只刷 `last_seen`（每轮巡检只保留首条）；该沉淀行为由回归测试锁定防回退。
- 处置后静默期：`(spec, signal_type)` 最近一条 `kind=disposition` 且 `result∈{resolved, partially-resolved}` 的记录时刻起，`admin.stuck_silence_minutes`（默认 120）内不产生信号；静默期后状态仍异常时允许新信号。
- escalated 处置不触发静默：admin 升级人工后同信号继续正常产生——人工处置是唯一出路。
- 真 stuck 不受影响：无存活 run、无文件活跃、无近期 resolved 处置时正常产生信号，不静默。
- 配置：`admin.stuck_silence_minutes` 默认 120、非负护栏，属受管键，在 Dashboard 系统设置面板可读可写。

## 溯源

- 2026-09-21 evo-stuck-signal-hygiene — 固化进程存活反证、merge_signal 去重回归锁定、resolved/partially-resolved 处置后静默期与 escalated 边界、`admin.stuck_silence_minutes` 配置与系统设置面板接线

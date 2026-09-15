# stuck-signal-hygiene — stuck 信号活跃度预检与去重

## 场景：run 文件近期增长但 spec.updated 停滞（长任务）

- 行为：_has_recent_progress 判定通过（8e510a87 后 -r<n> 子 run 可解析）→ 非 stuck；叠加进程存活检查：对应 agent 子进程存活（run 元数据/转录携带 pid）→ 非 stuck，不产生信号。

## 场景：同 (spec, signal_type) 未处置重复触发

- 行为：信号记录层冷却去重——同一 (spec, signal_type) 在冷却窗口（= cooldown_minutes，默认 60）内不重复落 signal 记录（每轮巡检只保留首条）。

## 场景：处置 resolved 后复发

- 行为：resolved 处置后静默期（admin.stuck_silence_minutes，默认 120）内同 (spec, signal_type) 不再产生信号；静默期后允许新信号（状态仍异常时）。

## 非目标

- 不改 stuck 主判据（updated 超阈值）本身；不改 baseline reset（extension）机制。
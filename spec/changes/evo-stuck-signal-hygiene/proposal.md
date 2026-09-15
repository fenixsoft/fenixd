# stuck-signal-hygiene — stuck 信号活跃度预检与去重

## Why

2026-09-14 fix-command-main-serve-scope 在 implementer 活跃期间 15:11-15:31 连发 5 条 stuck 升级告警（每 5 分钟一条、全程 unhandled、噪音 20 分钟）；同日 evo-verifier-result-single-source 17:56 再触发，admin 只读诊断确认「implementer 活跃跑全量回归」纯误报（诊断耗时约 2h40m 的 run 资源）。根因一（_spec_from_run_id 无法解析 -r<n> 瞬态重试后缀致 _has_recent_progress 匹配不到活跃 run 文件）已于 09-15 02:22 由 8e510a87 修复；残余缺口：① 信号记录层无去重（_throttled 仅在唤起路径生效，信号每轮照录——5 连发实证）；② 处置 resolved 后无静默期去重；③ 无 PID 存活检查（转录文件停止增长但进程存活的边界场景仍会误报）。

## What Changes

- stuck 判定叠加进程存活检查：对应 run 的 agent 子进程存活（os.kill(pid, 0)）即非 stuck。
- 信号记录层冷却去重：同一 (spec, signal_type) 在冷却窗口内不重复落 signal 记录（5 连发场景压缩为 1 条）。
- 处置 resolved 后静默期（默认 2 小时）内同 (spec, signal_type) 不复发信号。

## 验收

- 回放：活跃 implementer + 可解析 run_id → 0 误报；5 连发场景压缩为 1 条信号；处置 resolved 后同信号 2 小时内不复发。
- 真实 stuck（无进程 + 无文件活跃）仍正常产生信号。
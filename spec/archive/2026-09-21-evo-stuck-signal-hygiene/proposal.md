# stuck-signal-hygiene — stuck 信号活跃度预检与处置后静默

## Why

2026-09-14 `fix-command-main-serve-scope` 在 implementer 活跃期间 14:46–15:31 连发 11 条 stuck 信号（其中 15:06/15:11/…/15:31 共 6 条每 5 分钟一条、全程 unhandled，噪音约 45 分钟）；同日 `evo-verifier-result-single-source` 17:56 再触发，admin 只读诊断确认「implementer 活跃跑全量回归」纯误报。

⚠️ **两条主根因在评审前已修复，不属本 SPEC 范围**（首版方案误将其列为本 SPEC 目标，评审已否决）：

- **主根因**：`_spec_from_run_id` 无法解析 `-r<n>` 瞬态重试后缀 → `_has_recent_progress` 匹配不到活跃 run 文件 → 误判「无 run 进度」。**2026-09-15 02:22 由 8e510a87 修复**。
- **去重根因**：09-14 连发发生在 `merge_signal`（admin-signal-consolidation：`_handle_signal` 按 `(spec, signal_type, status_hash)` 状态沉淀，同状态续报只刷 `last_seen`、不新增记录）**上线之前**（09-15 08:09 提交 / 09:59 合并）。故「5 连发压缩为 1 条」**已由既有机制覆盖，不需新增去重代码**。

本 SPEC 只处理**残余缺口**：

1. **进程存活边界**：转录文件停止增长（mtime 超出宽限）但 agent 子进程仍存活的边界场景，现行 `_has_recent_progress` 纯按文件 mtime 判据仍会误报。
2. **处置后静默期缺失**：resolved 处置后同一 `(spec, signal_type)` 可立即复发产生新信号。
3. **新配置项缺 Dashboard 界面**：新增 `admin.*` 受管键必须同步系统设置面板。

## What Changes

- **D1 进程存活反证**：stuck 判定前，若该 spec 存在登记在跑且进程存活的 run（`AgentRunner.running_run_ids()` — 既有公开 API，以进程表 `_running_agents` 为真相）→ 判定非 stuck，直接跳过。
- **D2 不新增去重代码**：明确信号记录层去重由既有 `merge_signal` + `_throttled` 承担；本 SPEC 仅补**回归测试**锁定「冷却窗口内同 `(spec, signal_type, status_hash)` 只保留 1 条 signal 记录」行为，防止回退。
- **D3 处置后静默期**：`(spec, signal_type)` 最近一次 `kind=disposition` 且 `result∈{resolved, partially-resolved}` 记录时刻起，`admin.stuck_silence_minutes`（默认 120）内不产生信号。
- **D4 配置与界面**：`core/config.py` 新增 `admin.stuck_silence_minutes`（默认 120、非负护栏），并接入 `core/dashboard/data.py` 受管键白名单与 `SystemPanel.tsx` 系统设置面板。

## 验收

- 回放：spec 有登记在跑的存活 run（即使 run 文件 mtime 陈旧）→ 0 stuck 信号（D1）。
- 冷却窗口内同 `(spec, signal_type, status_hash)` 重复触发 → 只保留 1 条 signal 记录（D2 回归测试）。
- `result=resolved` 处置后 `stuck_silence_minutes` 内同 `(spec, signal_type)` 不产信号；窗口外状态仍异常时允许新信号（D3）。
- 真实 stuck（无存活 run + 无文件活跃 + 无近期 resolved 处置）仍正常产生信号（不掩真阳性）。
- `admin.stuck_silence_minutes` 在 Dashboard 系统设置面板可读可写（D4）。

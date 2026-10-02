<!-- knowledge: capability=admin-monitor rev=1 sources=spec/archive/2026-09-22-evo-orphaned-state-probe-calibration -->

# 异常状态探测口径（admin monitor 探针）

orphaned_state 无驱动探测的可见性口径：run 前缀归一、进程存活探测覆盖面与 admin 处置失败证据。

## 现行规则

- run_id 前缀归一按真源全量前缀（`core/agent_runner/run_files.py` 的 `RUN_ID_AGENT_PREFIXES`）还原 spec 名：spec-review/repair/planner/admin 等全部 run 前缀都能还原；`_has_recent_spec_run` 据此识别活跃 run。
- 失败计数前缀子集与归一前缀分离：`_RUN_PREFIXES` 只作计入失败统计的前缀子集（含 `repair-`，不含 `planner-`/`test-`），前缀归一改造不连带改变 `repeated_failures` 计数口径。
- 进程存活探测 `_pgrep_live_worktree` 的匹配集覆盖 `repair-<spec>-`（含 event_bus 孪生）；orphaned_state 三条件判定结构不变（无活动 run / 无存活子进程 / 无待派发）——任一前缀（含 repair-）的 run 文件 mtime 在宽限内即非孤儿。
- admin 处置 run（run_administrator）非零退出时，失败证据包含原始 stderr 摘录、退出码、provider/model 与末 3 条带 timestamp 的事件时间线，不再只留 `Exit code: N`；原始 stderr 只进证据字段，不回填 error 归因文本（error-attribution-denoise 的降噪语义保持）。
- 告警生命周期语义：signal / disposition pending / disposition failed / escalated 属同一信号的不同阶段，阶段差异由 description 与 status 区分；窗口查重（`AdminStore.latest_signal` → `_throttled`）冷却过期后同信号重新成条属既有语义，不视为重复告警缺陷。

## 溯源

- 2026-09-22 evo-orphaned-state-probe-calibration（spec/archive/2026-09-22-evo-orphaned-state-probe-calibration） — 修复活跃 repair run 双探测失明的误报：前缀归一全量化、存活探测覆盖 repair、admin 失败 run 证据补全与信号生命周期语义文档化

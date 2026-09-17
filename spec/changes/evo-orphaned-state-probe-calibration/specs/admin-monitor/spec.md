# admin-monitor Capability Spec

## 变更点

- run_id 前缀归一按真源全量前缀（core/agent_runner/run_files.py:RUN_ID_AGENT_PREFIXES）还原 spec 名，spec-review/repair/planner/admin 等全部 run 前缀都能还原；`_has_recent_spec_run` 据此识别活跃 run。
- 失败计数前缀子集与归一前缀**分离**：`_RUN_PREFIXES` 保留原语义（计入失败统计的前缀子集，补入 `repair-`，`planner-`/`test-` 不计），避免归一改造连带改变 `repeated_failures` 计数口径。
- 进程存活探测覆盖 repair 通道：`_pgrep_live_worktree` 匹配集加入 `repair-<spec>-`（含 event_bus 孪生），条件 ② 对活跃 repair run 不再失明。
- admin 处置 run（run_administrator）非零退出时，失败证据含原始 stderr 摘录、退出码、provider/model 与末 3 条带 timestamp 事件时间线，不再只留 `Exit code: N`；原始 stderr 只进证据字段，不回填 error 归因文本（error-attribution-denoise D5 语义不变）。
- 告警生命周期语义文档化：signal / disposition pending / disposition failed / escalated 属同一信号的不同阶段，阶段差异由 description 与 status 区分；窗口查重（AdminStore.latest_signal → `_throttled`）保持现状（冷却过期后同信号重新成条属既有语义，不视为重复告警缺陷）。

## 判定语义

- 任一 run 前缀（含 repair-）的 run 文件 mtime 在宽限内 → 非孤儿。
- 无任何 run 活跃 + 无存活子进程（含 `repair-<spec>-`）+ 无待派发 → orphaned_state（三条件结构不变）。
- admin 处置失败必有可定位证据：原始 stderr 摘录 / 退出码 / provider·model / 带时间戳事件时间线。

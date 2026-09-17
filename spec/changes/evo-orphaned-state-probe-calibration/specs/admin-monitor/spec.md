# admin-monitor Capability Spec

## 变更点

- run_id 前缀归一改用与 run_files.py:RUN_ID_AGENT_PREFIXES 同源的全量前缀（或直接补 `repair-`），spec-review/repair/planner/admin 等全部 run 前缀都能还原 spec 名；`_has_recent_spec_run` 据此识别活跃 run。
- admin 处置 run（run_administrator）非零退出时，错误日志包含 CLI stderr 摘录/退出码/最近事件时间线，不再只留 `Exit code: N`。
- 告警生命周期语义文档化：signal / disposition pending / disposition failed 属同一信号的不同阶段，不重复计数；窗口查重（AdminStore.latest_signal）保持。

## 判定语义

- 任一 run 前缀（含 repair-）的 run 文件 mtime 在宽限内 → 非孤儿。
- 无任何 run 活跃 + 无存活子进程 + 无待派发 → orphaned_state（现状）。
- admin 处置失败必有可定位日志。
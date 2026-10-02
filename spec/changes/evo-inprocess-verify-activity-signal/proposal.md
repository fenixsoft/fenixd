# Proposal: inprocess-verify-activity-signal

## Why

全量验证自 verify_engine 三段流水线起改为 in-process 执行（daemon 线程 fenix-verifier-<spec> 内 asyncio.run，无 verify-<spec>-*.jsonl run 文件、无独立子进程），而 spec_is_undriven（core/admin_monitor.py:706-778）四条件只认「外置 run 形态」：①run 文件 mtime、②pgrep worktree 子进程、③有意等待、④派发队列。2026-10-02 cimbar-airgap-transfer 实证后果：验证活跃期被误判孤儿态两条告警（17:50:36/18:35:37 本地），recovery 出口（event_bus.py:439）与处置复位直通道（admin_monitor.py:4679）先后重派，三个 23 场景全量批交错执行，外加 $1.289 admin 调查 run（admin-cimbar-airgap-transfer-1790934636）。写侧活性信号其实已存在——verify_engine 的 _write_progress（engine.py:706-733）起跑/逐场景/终态原子写 .fenix/verify-progress/<spec>.json——缺的只是判定读侧不消费。

## What Changes

- spec_is_undriven 新增条件⑤「daemon 进程内 verifier 线程活跃」：threading.enumerate() 命中 fenix-verifier-<spec>（线程名出处 core/pm_engine/dispatch/queue.py name=f"fenix-{agent_type}-{spec_name}"）即判有驱动；零调参、不依赖时间窗。
- 条件①活动文件口径扩展：把 .fenix/verify-progress/<spec>.json（既有逐场景原子写）mtime 纳入，用独立活动窗口（默认对齐孤儿阈值 15 分钟），不沿用 120s run 宽限（单场景长批间隔实测 4-5 分钟，会假阴性）。
- 处置复位直通道（_reset_orphaned_after_disposition testing 分支，不过判定函数的第三出口）重派前增加在飞验证复核，命中即顺延。
- docstring 按既有记忆惯例增补条件⑤由来（本次实证），替代「只记条件④」的历史口径。

## 非目标

- 不改 verify_engine 写侧（进度文件已按需原子写，无新增心跳）。
- 不以 PMEngine._active_runs 计数为判据（有泄漏史、不可单独信赖）。
- 不改 orphaned_state 阈值与告警级别、不动 legacy 外置 verifier 车道（其本就被条件①②覆盖）。
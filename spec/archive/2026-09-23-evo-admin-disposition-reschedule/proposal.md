## Why

AdminMonitor 的孤儿处置检测（_recover_orphaned_dispositions，core/admin_monitor.py:1557）在「admin run 因 daemon 优雅退出（known shutdown）被中断」时，只把 pending disposition 终结为 interrupted（1600-1627），既不重派底层信号也不升级人工——而信号的自动唤起已被冷却节流（_throttled，core/admin_monitor.py:1376）压制，导致被中断处置的真实用户请求永久悬空，直到人工介入。

实证（fenix-desktop 2026-09-17）：信号 f8df40b7e4f0（verify_contract_missing，UI 手动触发，created 09-09）经 09-13 中断与 09-17 孤儿终结后仍 handled=false，请求悬空 8 天；disposition 4913cd88bcc6 于重启后 0.8s 被标记 interrupted 终结，无重派。

同类机制在本仓库亦可复现（.fenix/admin_alerts.json）：run `admin-refactor-giant-classes-1789664978` 的 pending disposition 于 2026-09-17T17:55:28 被终结为 interrupted，而其底层信号 `bfbcffb0b07a`（blocked_stuck，escalated=true）至今 handled=false。

任何「daemon 在 admin run 在飞时停机」的复发都会重演同样的永久悬空。

## What Changes

- 孤儿检测的「已知中断」分支（core/admin_monitor.py:1600）升级：判定 run 含 interrupted 标记后，先回溯该 disposition 关联的底层信号（kind=signal ∧ signal_type 相同 ∧ spec 严格相等 ∧ escalated=true ∧ 非 handled）是否仍存在；存在 → 自动重新入队一个 admin run，而非终结。
- 重派入口：直接复用 _invoke_administrator(signal, signal_rec)（core/admin_monitor.py:1764），**不经 _handle_signal**——否则 _throttled（1376）会把重派吞掉（同 _retry_due_dispatch_failures 的既有先例，core/admin_monitor.py:1551）；signal 由 _rebuild_dispatch_signal（2125）从信号记录重建。
- 重派有界：每有一个「重派后的 run 再次被中断」才可再重派一次，累计重派次数（reschedule_count，落库字段）超限（默认 2）后转人工升级（kind=escalation，severity=critical），防止停机循环无限重派烧钱。
- 幂等与并发安全：重派前用**新增**的 _has_active_admin_run_for(spec, signal_type)（判据：同 (spec, signal_type) 存在 status=pending 的 disposition 记录，对齐 by_run 归并口径）判该信号是否已有在飞/待派发 run，避免双重派发。
- 审计留痕：原 pending disposition 追加 status=superseded 记录并携带 reschedule_count（保留审计链，兼作计数载体）；**不额外写** status=dispatched 的新 disposition——重派 run 的处置记录由 run_administrator 自身落的 pending 记录承载（core/agent_runner/maintenance_runs.py:182），额外写一条同 admin_run_id 的非 pending 记录会让孤儿检测的 by_run 归并把该 run 判为已终结，使后续中断永不被检测、计数上限永不生效。
- 超限分支与「未找到信号」分支均须为该 run 追加非 pending 终结 disposition（沿用 1643-1660 既有做法），否则同一孤儿每轮巡检重复升级。

## Capabilities

### New Capabilities

- `admin-disposition-reschedule`: AdminMonitor 孤儿检测在已知中断（known shutdown）处置后，自动重新入队底层未处理信号的管理员 run；中断-重派闭环，超限升级人工。

### Modified Capabilities

- `admin-monitoring`（AdminMonitor 孤儿处置 _recover_orphaned_dispositions）: 「已知中断终结」由无恢复的终态改为「先查信号 → 重派或升级」。

## Why

AdminMonitor 的孤儿处置检测（_recover_orphaned_dispositions，core/admin_monitor.py:1431）在「admin run 因 daemon 优雅退出（known shutdown）被中断」时，只把 pending disposition 终结为 interrupted，既不重派底层信号也不升级人工——而信号的自动唤起已被冷却节流（_throttled）压制，导致被中断处置的真实用户请求永久悬空，直到人工介入。

实证（fenix-desktop 2026-09-17）：信号 f8df40b7e4f0（verify_contract_missing，UI 手动触发，created 09-09）经 09-13 中断与 09-17 孤儿终结后仍 handled=false，请求悬空 8 天；disposition 4913cd88bcc6 于重启后 0.8s 被标记 interrupted 终结，无重派。

任何「daemon 在 admin run 在飞时停机」的复发都会重演同样的永久悬空。

## What Changes

- 孤儿检测的「已知中断」分支升级：判定 run 含 interrupted 标记后，先回溯该 disposition 关联的底层信号（同 spec + signal_type 且 kind=signal）是否仍 handled=false；若是 → 自动重新入队一个 admin run（复用现成派发入口），而非终结。
- 重派有界：同一 disposition 每有一个后续 run 被中断才可再重派，累计重派次数超限（默认 2）后转人工升级，防止停机循环无限重派烧钱。
- 幂等与并发安全：重派前检查该信号是否已存在在飞/待派发的 admin run（复用去重判定），避免双重派发。
- 审计留痕：重派时更新 disposition（新 admin_run_id，status=dispatched），actions_taken 注明 reschedule_from_id；原 pending disposition 置 status=superseded（保留审计链）。

## Capabilities

### New Capabilities

- `admin-disposition-reschedule`: AdminMonitor 孤儿检测在已知中断（known shutdown）处置后，自动重新入队底层未处理信号的管理员 run；中断-重派闭环，超限升级人工。

### Modified Capabilities

- `admin-monitoring`（AdminMonitor 孤儿处置 _recover_orphaned_dispositions）: 「已知中断终结」由无恢复的终态改为「先查信号 → 重派或升级」。

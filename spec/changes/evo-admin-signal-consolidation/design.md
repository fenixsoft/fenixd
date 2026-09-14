# 设计 — admin-signal-consolidation

## 记录模型
- admin_alerts 信号记录增加 status_hash（sha1(spec.status + error + updated)）、first_seen、last_seen。
- admin_monitor 检查时：计算当前 status_hash，与同 spec 同类型现存未 handled 信号比较；相同则仅更新 last_seen 与 created 语义（created 保留首次），不同则新建记录。

## 强制升级判据
- 信号首次触发时间距当前 ≥2h 且无任何 disposition/escalation 指向该 (spec, signal_type) 结果时，绕过 cooldown 直接升级人工（severity critical）。
- 现有 escalation_cooldown_minutes 仅约束「同类型重复升级」，悬置强制升级与之正交。

## 改动点
- .fenix/core/admin_store.py：信号记录字段扩展与去重合并逻辑。
- .fenix/core/admin_monitor.py：状态哈希判定 + 悬置 ≥2h 强制升级。
- .fenix/core/dashboard/data.py：信号按 (spec, signal_type) 去重聚合展示。
# 任务

## Deliverables

```yaml
- path: core/admin_store.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
```

## 1. 信号记录扩展 status_hash/first_seen/last_seen 与去重合并

- [ ] 1.1 core/admin_store.py：存储层支持同 (spec, signal_type) 状态未变时合并更新 last_seen，不新增记录；写单元测试覆盖「状态未变仅更新 last_seen」「状态变化新建记录」。

## 2. admin_monitor 状态哈希判定与悬置 ≥2h 强制升级

- [ ] 2.1 core/admin_monitor.py：计算 status_hash 判定状态未变；悬置 ≥2h 且无处置结果时强制升级人工（绕过 cooldown）；写测试覆盖 9.5h 悬置重放场景。

## 3. dashboard 信号去重聚合展示

- [ ] 3.1 core/dashboard/data.py：信号列表按 (spec, signal_type) 聚合，显示 first_seen→last_seen 区间与状态哈希，替代逐条刷屏。

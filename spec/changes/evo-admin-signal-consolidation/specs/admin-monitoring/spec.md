# 监控信号状态沉淀（admin-signal-consolidation）

## 需求

### R1 状态沉淀
- admin_monitor 对同一 (spec, signal_type) 组合维护唯一信号记录，附 first_seen 与 last_seen 时间戳。
- 状态哈希（spec 状态 + error 摘要 + updated 时间戳）未变时，发生事件仅更新 last_seen，不新增记录、不打重复日志。

### R2 悬置强制升级
- 同一 (spec, signal_type) 从未被实质处置（无 disposition/escalation 结果）且悬置 ≥2h 时，强制重复升级真人（不因 cooldown 节流丢弃）。
- 升级记录注明已悬置时长与首次触发时间，便于人工判定。

### R3 可观测
- 信号记录含 first_seen/last_seen/status_hash 字段；dashboard 可按 spec 聚合去重展示。

## 验收标准
- 场景：add-web-ui blocked 悬置 9.5h 重放时，信号记录 ≤2 条（初次 + 升级），而非 94 条。
- 单元测试：状态未变仅更新 last_seen；悬置 ≥2h 触发强制升级。
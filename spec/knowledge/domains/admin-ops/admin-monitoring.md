<!-- knowledge: capability=admin-monitoring rev=1 sources=spec/archive/2026-09-19-evo-admin-signal-consolidation -->

# 监控信号状态沉淀与悬置升级

admin_monitor 对同一 spec 同类型信号的「状态沉淀」取代逐轮新增记录，并对长期悬置的 blocked 强制升级真人。

## 现行规则

- 状态沉淀：同一 (spec, signal_type) 组合维护唯一信号记录，附 `first_seen`（即 created）与 `last_seen`；状态哈希（spec 状态 + error 摘要 + updated 时间戳）未变时，发生事件仅刷新 last_seen，不新增记录、不打重复日志；合并不改写 id/created/escalated/handled。
- 沉淀仅作用于 admin_monitor 的 per-spec 检测信号；「写入即待唤起」型记录（`STORED_SIGNAL_TYPES` 按 id 摄取）与 `kind=escalation` 告警不参与合并（id 是 mark_escalated / mark_handled 的锚点）。
- 冷却窗口判定 `latest_signal` 必须覆盖 last_seen（取 `max(created, last_seen)`），使既有 `_throttled` 节流对持续信号仍生效，不因沉淀而在冷却期满后每轮巡检重复唤起 Administrator。
- spec 为 None 的 daemon 级信号按同口径沉淀（状态哈希用回退判据）或显式排除，二者择一，不抛异常。
- 悬置强制升级：仅限悬置类信号（blocked_stuck 含 ENV 阻塞族），其余信号类型维持冷却节流。悬置时长 = now − spec.updated，达 2 小时（模块常量，不入 config）且同 (spec, signal_type) 无未处理人工升级告警时，绕过 escalation_cooldown_minutes 写一条 `kind=escalation`（severity=critical）直接升级真人，不重新唤起 Administrator。
- 已有未处理升级告警期间不新增（防升级风暴）；人工处理后状态仍悬置且达阈值可再次升级，每次人工处理后至多一条；升级记录注明已悬置时长与首次触发时间。
- 沉淀效果经既有消费端体现（自省报告 admin 摘要的信号计数、admin_alerts 的 MAX_RECORDS 裁剪窗口），不新增 dashboard 聚合端点。

## 溯源

- [2026-09-19 evo-admin-signal-consolidation](spec/archive/2026-09-19-evo-admin-signal-consolidation/) — 同 spec 同类型信号由逐轮新增改为状态沉淀（first_seen/last_seen/status_hash），blocked 悬置 ≥2h 突破节流强制升级

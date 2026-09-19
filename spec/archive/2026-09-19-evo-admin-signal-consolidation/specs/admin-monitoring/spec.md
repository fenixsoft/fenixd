# 监控信号状态沉淀（admin-signal-consolidation）

## 需求

### R1 状态沉淀
- admin_monitor 对同一 (spec, signal_type) 组合维护唯一信号记录，附 first_seen 与 last_seen 时间戳；first_seen 即现有 `created`，last_seen 每次同状态发生即刷新。
- 状态哈希（spec 状态 + error 摘要 + updated 时间戳）未变时，发生事件仅更新 last_seen，不新增记录、不打重复日志；合并不得改写 id/created/escalated/handled。
- 沉淀仅作用于 admin_monitor 的 per-spec 检测信号；「写入即待唤起」型记录（STORED_SIGNAL_TYPES 按 id 摄取）与 `kind=escalation` 告警不参与合并（id 是 mark_escalated / mark_handled 的锚点）。
- `latest_signal` 冷却窗口判定 MUST 覆盖 last_seen（`max(created,last_seen)`），使沉淀后既有 `_throttled` 节流对持续信号仍生效；否则超过 cooldown 后每轮巡检都会重新唤起 Administrator。
- spec 为 None 的 daemon 级信号同口径沉淀，status_hash 采用回退判据或显式排除，二者择一。

### R2 悬置强制升级
- 范围仅限悬置类信号：blocked_stuck（含 ENV 阻塞族）。其他信号类型维持既有 cooldown 节流。
- 悬置时长 = now − spec.updated，≥2h 且同 (spec, signal_type) 无**未处理**人工升级告警时，绕过 escalation_cooldown_minutes 写一条 `kind=escalation`（severity critical），直接升级真人；不重新唤起 Administrator。
- 阈值 2h 为模块常量（不入 config）。
- 已有未处理升级告警期间不新增（防升级风暴）；人工处理后状态仍悬置且 ≥2h → 可再次升级，每次人工处理后至多一条。
- 升级记录注明已悬置时长与首次触发时间，便于人工判定。

### R3 可观测
- 信号记录含 first_seen/last_seen/status_hash 字段，可供既有消费端读取。
- 沉淀效果经既有消费端体现：自省报告 admin 摘要的「信号 N 条」（core/self_review.py:688）与 admin_alerts 的 MAX_RECORDS 裁剪窗口（core/admin_store.py:31-34）。不新增 dashboard 聚合端点（现无 signal 消费端，新增即死代码）。

## 验收标准
- 场景：add-web-ui blocked 悬置 9.5h 重放时，信号记录 ≤2 条（初次 + 升级），且期间不重新唤起 Administrator、不产生升级风暴（未处理升级存在时不再新增）。
- 场景：状态未变且持续多轮巡检、跨越 cooldown 窗口（>60m）后，Administrator 不被重复唤起（latest_signal 锚点覆盖 last_seen 生效）。
- 场景：spec=None 的 daemon 级信号按声明口径沉淀或排除，无 KeyError/无意外合并。
- 单元测试：状态未变仅更新 last_seen；状态变化新建记录；非悬置类信号悬置 >2h 不触发强制升级；悬置 ≥2h 触发一次强制升级；未处理升级存在时不重复升级；人工 handled 后仍悬置可再次升级。

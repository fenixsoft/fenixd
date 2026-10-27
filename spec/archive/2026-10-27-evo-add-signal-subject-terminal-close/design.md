## Context

主体终态闭环现状：判定端 core/alert_lifecycle.py（evaluate_alert :328-329 kind 门；CONDITION_SPEC_TERMINAL_OR_UNBLOCKED；BACKFILL_SIGNAL_TYPES :59 与 _SIGNAL_CONDITIONS :107 已含 blocked_stuck；TERMINAL_SPEC_STATUSES :40）；盘点通道 core/admin_monitor.py _run_alert_lifecycle（L2213，pending 过滤 :2243 只收 kind=escalation）；写回端 core/admin_store.py auto_resolve（L680/:697 kind 门）与 auto_self_heal（L715，已支持 kind=signal，可比照）；既有署名 AUTO_RESOLVE_BY。终态查询：_run_alert_lifecycle 已持有当轮 STATE.md 状态表；admin_monitor.py:2486 有 read_one(spec) 用例；:2488-2493 既有终态守卫只覆盖 STORED_SIGNAL_TYPES 摄取族且只 mark_escalated。信号落库形态：blocked_stuck 为 kind=signal（_detect_blocked_stuck L2387 造信号，:3949-3951 merge_signal escalated=True）。

## Goals / Non-Goals

- Goals：spec 附着族 kind=signal 信号随主体终态惰性收口；台账不再虚报已自愈升级。
- Non-Goals：不动注册表与安静锚；不覆盖处置组升级；不改触发/升级阈值。

## Decisions

- D1 选「放宽既有闭环 kind 门」（案 A）而非「纳入自愈注册表」（案 B）：案 B 字面不成立——注册表无主体终态锚位，且带 trigger 的新形态会被 find_self_healable 以「条件在册」跳过、find_resolvable 又受 kind 门；案 A 扩展点现成（specs 状态表已入参），三处单点修改。
- D2 收口范围按条件族白名单而非全部 kind=signal：仅 trigger/登记条件属 spec 附着族（spec_terminal_or_unblocked 等）的记录走终态判定，防「主体终态但仍需人工关注的信号」被误收口。
- D3 写回比照 auto_self_heal（已支持 kind=signal）或放宽 auto_resolve kind 门，handled_by 沿用 AUTO_RESOLVE_BY，注记附主体终态时刻便于审计。

## Risks / Trade-offs

- 误收口风险由条件族白名单兜底：非 spec 附着信号（daemon_errors 等瞬态族）仍走安静锚。
- 盘点每轮多读 spec 状态：_run_alert_lifecycle 已持有当轮状态表，零额外 IO。
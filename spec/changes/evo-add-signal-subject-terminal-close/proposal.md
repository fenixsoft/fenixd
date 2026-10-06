## Why

spec 级滞留信号不随主体终态收口：blocked_stuck 信号 a90ebc0e80a8 在主体 spec 已转 pushed（22 分钟自愈）后 escalated/handled=False 挂 3.5 天，台账虚报人工升级。主体终态自动解除闭环（add-alert-auto-resolve，2026-08-30）其实已建成且 blocked_stuck 条件在册，但其判定端（core/alert_lifecycle.py:328）、盘点通道（core/admin_monitor.py:2243）、写回端（core/admin_store.py:697）三处 kind 门禁只放行 kind=escalation，blocked_stuck 落库形态是 kind=signal，结构性不可达。另核实条目备选「纳入 SELF_HEAL_SIGNAL_TYPES」字面不成立：注册表是纯类型元组+固定签名安静锚，无主体终态锚位，且带 trigger 的新形态会被 find_self_healable 跳过。

## What Changes

1. 判定端：evaluate_alert 对 kind=signal 且属 spec 附着条件族（trigger/登记条件为 spec_terminal_or_unblocked 等）的记录走既有主体终态判定，签名安静族语义不动。
2. 盘点通道：_run_alert_lifecycle 的 pending 集纳入未 handled 的该族 kind=signal 记录。
3. 写回端：auto_resolve 放宽到 escalation+signal（或比照 auto_self_heal 新增 signal 写回），handled_by 沿用既有自动收口署名，收口注记附主体终态时刻。

## Out of Scope

- 不动 SELF_HEAL_SIGNAL_TYPES 注册表与签名安静锚语义（瞬态类自愈不受影响）。
- 不覆盖处置组形态的升级滞留（如 admin 处置组 fail-closed 升级，主体非 spec）。
- 不改 blocked_stuck 的触发阈值与升级链路。
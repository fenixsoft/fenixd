<!-- knowledge: capability=spec-timeline-admin-events rev=1 sources=spec/archive/2026-09-12-add-timeline-admin-events -->

# 时间轴 admin 事件

SPEC 时间轴接入升级告警与运维处置记录，与状态/运行节点混合按事件时间排序。

## 现行规则

- 事件来源：`get_spec_timeline` 从 `.fenix/admin_alerts.json` 读取 `spec` 字段与当前 SPEC 名一致的 `escalation`（升级告警）与 `disposition`（运维处置）记录，每条生成一个 `kind="admin"` 的时间轴节点；节点携带时间（`created`）、`kind`、`record_kind`（escalation/disposition）、`signal_type`、`severity`、`description` 与处置/处理状态（escalation 取 `handled`，disposition 取 `result`）；`signal` 类内部审计记录不下发到时间轴。
- SPEC 隔离：其他 SPEC 的运维事件不串扰到当前 SPEC 时间轴。
- pending 归并：同 `admin_run_id` 的 disposition 记录中存在非 pending 的最终处置时，pending（处置中）记录被最终记录替代，时间轴仅保留最终处置节点；无最终处置时 pending 以「处置中」状态独立成节点；无 `admin_run_id` 的 pending 记录按独立事件保留。
- 排序与折叠：admin 节点与 state、run 节点共用同一排序规则（`_timeline_sort_key`）——按事件时间排序，同一秒内按 state → admin → run 次序排列；连续前向状态转移的折叠被 admin 节点打断，admin 节点自身不参与折叠。
- 前端渲染：admin 节点渲染为紧凑运维卡片——标题行含时间、「运维处置」（disposition）或「升级告警」（escalation）标签、severity 着色 Tag（critical 红 / major 橙 / warning 及以下灰）与状态 Tag（disposition：已解决绿、处置中蓝；escalation：已处理/未处理），标题行下方展示一句话摘要（`description`，超长截断）；不在时间轴卡片内渲染 `summary` markdown 全文（完整四段总结仍由运维记录页承载）；未知 `kind` 走安全默认分支（按既有行为渲染或忽略），不报错。
- fail-open：`.fenix/admin_alerts.json` 缺失、损坏或读取异常时时间轴构建不报错，照常下发 state 与 run 两类节点（admin 事件为空）；admin 记录缺失 `spec` 字段时跳过该记录，不误挂到当前 SPEC。

## 溯源

- 2026-09-12 add-timeline-admin-events — 时间轴接入 admin 运维事件：escalation/disposition 节点下发、pending 处置归并、同秒排序次序、紧凑运维卡片渲染与告警源缺失 fail-open

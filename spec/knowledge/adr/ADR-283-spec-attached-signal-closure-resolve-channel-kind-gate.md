# ADR-283：spec 附着信号终态收口归 auto-resolve 通道，自愈注册表不承载主体终态锚

date: 2026-10-27
status: accepted

## Context

spec 级滞留信号不随主体终态收口：blocked_stuck 信号在主体 spec 已转 pushed（自愈完成）后仍以 escalated/handled=False 挂留多日，台账虚报人工升级。主体终态自动解除闭环（auto-resolve）已建成且 blocked_stuck 条件在册，但其判定端（evaluate_alert）、盘点通道（_run_alert_lifecycle pending 过滤）、写回端（AdminStore.auto_resolve）三处 kind 门禁只放行 kind=escalation，而 blocked_stuck 落库形态是 kind=signal，结构性不可达。备选方案「纳入 SELF_HEAL_SIGNAL_TYPES 自愈注册表」字面不成立：注册表是纯类型元组＋固定签名安静锚，无主体终态锚位，且带 trigger 的新形态会被 find_self_healable 以「条件在册」跳过、find_resolvable 又受 kind 门，两头落空。

## Decision

spec 附着信号的终态收口归 auto-resolve 通道：同步放宽既有闭环三处 kind 门（判定端、盘点通道、写回端），kind=signal 仅当属 spec 附着条件族（spec_terminal_or_unblocked 等已登记条件）时走既有主体终态判定，kind=escalation 语义逐位不动。自愈注册表保持纯类型元组，不新增主体终态锚位——任何「随主体恢复而收口」的新信号需求一律扩展 auto-resolve 条件族，不进 SELF_HEAL_SIGNAL_TYPES。收口范围按条件族白名单界定而非全部 kind=signal，防「主体终态但仍需人工关注的信号」被误收口。

## Consequences

- 两通道边界固化：auto-resolve 承载 spec 附着条件族（escalation+signal 双 kind），auto-self-heal 承载瞬态族签名安静锚（注册表纯类型）；瞬态族信号（daemon_errors 等）不随任何 spec 终态收口，非 spec 附着信号仍走安静锚或人工闭环。
- 判定端、盘点通道、写回端三处必须同步放行，缺一处即「结构性不可达」复发；族判定须单源共享谓词（判定端 kind 门与盘点 pending 过滤同一函数），防两侧口径漂移。
- 收口注记由判定端生成并附主体终态/解除时刻（specs 状态表 entry 的 updated 字段），写回端只透传不另造内容——原始事故形态之一是收口记录无时刻可对账，审计可回查是硬要求。
- 处置组形态的升级滞留（主体非 spec）仍不在自动收口覆盖面，须人工闭环；blocked_stuck 的触发阈值与升级链路不受本裁定影响。

# ADR-101：空 SPEC 内容完整性闸门挂派发前，命中即冻结告警自闭环

date: 2026-09-17
status: accepted

## Context

派发路径只有「次数」维度的闸门（实现预算耗尽），没有「内容」维度——seeding 对空目录只记 WARNING 继续，实现 agent 拿到空 spec 只能拒绝产出，直到烧满预算才被拦。夹具实证：两条空占位 spec 各盲跑 6 轮（共 12 个 implementer run）才被预算闸门冻结。

## Decision

- 内容完整性闸门挂在派发资格链上（implementer / fast-track 分支与预算闸门同层），不在 seeding 层把关：seeding 失败是 non-fatal 设计、无法区分「合法空 spec」与「异常空 spec」，且 worktree 内动作不在派发资格链上；派发前是离状态翻转最近、命中即 blocked 的唯一可靠停靠点。
- 实质内容判定取宽松四选一：proposal / design / tasks / specs 下任一 .md 存在即视为有内容。覆盖全部合法形态（早期 draft 可只有 proposal），同时拦得住「空目录 / 只有无关文件」；严格要件会误伤早期形态。
- 闸门自身读目录异常保守放行（WARNING 后放行）：闸门的目标是拦空 spec，不是卡死派发；临时不可达宁可放行交预算闸门兜底，也不挡健康 spec。后续一切派发前预检沿用此校准——预检自身故障不阻塞派发。
- 命中处置复用冻结范式：blocked + human escalation 告警，并在告警生命周期注册解除条件（spec 离开 blocked / 进入终态即自动 resolve），补内容解冻无需人工清告警。

## Consequences

- 空 spec 第一轮派发前即冻结，预算零消耗；健康 spec 零误伤（宽松判定 + IO 异常放行）。
- 双闸门不重复告警：命中即 blocked 后，预算闸门因「已是 blocked」幂等返回，不重复升级。

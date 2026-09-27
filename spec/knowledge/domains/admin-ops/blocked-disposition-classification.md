<!-- knowledge: capability=blocked-disposition-classification rev=1 sources=spec/archive/2026-09-19-fix-blocked-freeze-classification -->

# blocked 冻结/阻塞二分类

blocked 停摆的分类契约：「冻结转人工」与「阻塞待 admin」二分，写入点机械化收敛，禁止裸 blocked。

## 现行规则

- 二分类契约：每次写入 `status=blocked` 时，该停摆必须显式归入两类之一，不存在两者皆无的裸 blocked。
- 冻结转人工（`frozen=True`）：admin agent 对根因无操作杠杆、需人在场决策的停摆（人工暂停、预算耗尽、内容缺失、评审否决/评审尝试耗尽、重启重验超限）；必须在写 blocked 的同一动作中发送人工升级告警。
- 阻塞待 admin（不写 frozen）：admin agent 可自动修复的停摆（改环境、起草契约、清 git 状态、merge-back 冲突等）；由 admin 巡检介入，`admin_monitor` 的 blocked_stuck 超时巡检仍会唤起 Administrator。
- 评审路径归冻结转人工：spec-review 的否决（`rejected`）与评审尝试耗尽（`spec-review-incomplete`）置 blocked 时必须写 `frozen=True` 并发人工升级告警（含否决 findings 摘要与评审 run id / 连续失败原因）；admin_monitor 不再对这类 spec 发起 blocked_stuck 唤起——防止对方案类停摆做无杠杆的重复介入。
- 自动冻结不得静默：任何自动路径冻结 spec 为 blocked 时必须同时发出人工升级告警（重启重验超限逐 SPEC 触发，不聚合丢失）；不存在「打了 frozen 标记但无人被通知」的静默冻结。
- 机械化收敛：`freeze_for_human(spec, signal_type, reason, ...)` helper 统一「frozen + alert」成对写入，各 blocked 写入站点经 helper 落地，不手写 `update_spec({status: blocked, frozen: True, ...})`。
- 文档契约：生命周期文档记录 blocked 的二分类语义、判据（admin 是否有杠杆）与各类消费者（admin 豁免 / dashboard 双标签 / 人工告警），新增写入点据此归类。

## 溯源

- 2026-09-19 fix-blocked-freeze-classification — 确立 frozen/阻塞二分类契约：评审路径改冻结转人工、静默冻结补告警、freeze_for_human 成对写入 helper 与文档判据

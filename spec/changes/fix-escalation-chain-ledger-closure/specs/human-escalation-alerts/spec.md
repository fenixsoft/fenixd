# 能力规格：人工升级告警——归因子型与 chain-closed 对账兜底

（修改既有能力 human-escalation-alerts，spec/knowledge/domains/admin-ops/human-escalation-alerts.md）

## ADDED Requirements

### Requirement: 孤儿升级归因读 result 子型

`_orphan_run_attribution` 对 result 终态 MUST 读子型区分两种形态：
- success 子型 → 归因写「处置结论成功但 final 处置记录缺失（落账缺口或收尾中断）——
  先核对处置台账与链事件再定处置」，MUST NOT 写「非成功结论」类与事实相反文案；
- 非 success 子型 → 保持既有「run 以 result 终态退出但处置未完成（非成功结论）」文案。

#### Scenario: success 子型归因

- **WHEN** 孤儿升级开火且 run 文件末事件为 `type=result, subtype=success`（复刻首例
  事件 …6474 形态）
- **THEN** 告警 description 归因段为「处置结论成功但 final 处置记录缺失」族文案，
  evidence 照常附终态摘录；不出现「非成功结论」字样

#### Scenario: 非 success 子型文案不变

- **WHEN** 孤儿升级开火且 run 文件末事件为 `type=result` 但子型非 success
- **THEN** 归因文案保持既有「非成功结论」表述（回归锚，不得回退）

### Requirement: 孤儿看护 chain-closed 对账兜底

孤儿看护 pending 分支（run 文件终态、非 interrupted、链痕 in_flight/deferred/arbiter
抑制未命中）升级人工前，MUST 查链事件台账——同 `admin_run_id` 存在
chain-closed / chain-handoff 事件时，MUST NOT 产生升级告警：补写一条非 pending 终结
DISPOSITION 记录闭合该 pending（`result=resolved`，`actions_taken` 注明「链侧已闭环但
final 记录缺失，由看护对账补记」），链事件台账查询异常（文件缺失/损坏）按零命中放行
升级（fail-open，对齐链痕抑制既有降级口径）。

#### Scenario: 链已闭环的孤儿 pending 不升级

- **WHEN** pending 超时 + run 文件 result 终态 + 链痕抑制未命中 + 链事件台账存在该
  run_id 的 chain-closed 事件（复刻首例事件 …6474 时间轴）
- **THEN** 不产生 escalation 告警；pending 被对账终结记录闭合，后续巡检不再重判

#### Scenario: 链 handoff 事件同样兜底

- **WHEN** pending 超时且链事件台账存在该 run_id 的 chain-handoff 事件（admin 转单后
  final 记录因历史缺口缺失的形态）
- **THEN** 同样对账终结不升级

#### Scenario: 查询异常 fail-open

- **WHEN** 链事件台账文件缺失或不可解析
- **THEN** 按零命中处理，孤儿升级照常发生（宁多告警不漏告警）

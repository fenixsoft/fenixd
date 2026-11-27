# 能力：全仓审查覆盖缺口执行层（code-review-lane）

## Requirement: 覆盖缺口终态降格与告警

全仓审查 run 收尾时，收尾守卫按既有权威口径（分片+主产物聚合，core/code_review.py covered_files）对 manifest scope 计算覆盖；当未覆盖文件比例超过阈值（缺省 2%，可配置）时，MUST：

1. 把该 run 终态从 success 降格记为 partial；
2. 经既有告警写回通道落一条告警，正文含未覆盖文件数与差集摘要（文件数过多时给计数与前若干例）；
3. 调用既有 pending-writeoff 锚写入（core/code_review.py write_pending_writeoff），使 core/admin_monitor.py 既有锚续审扫描自动武装 redispatch 续审。

未覆盖比例低于阈值时 MUST 保持现行为：WARNING 留痕、success 终态、不落锚。

## Requirement: 批次派发事件留痕

每个审查批次派出时，MUST 把批号与计划文件数落一行事件记录（随 manifest 或档案事件流），使「批号跳过/计划批次数偏短」形态可与 manifest scope 直接对账。该留痕不改变批次执行逻辑。

## Scenario: 干净收尾但覆盖超阈值

- WHEN 全仓审查 run 无打断干净收尾且覆盖缺口比例超过 2%
- THEN run 终态记 partial、告警落账、pending-writeoff 锚在册，下一轮锚续审扫描武装 redispatch 续审

## Scenario: 覆盖缺口低于阈值

- WHEN 收尾覆盖缺口比例不超过 2%
- THEN run 终态保持 success、不落锚、仅 WARNING 留痕

## Scenario: 批次计划偏短可对账

- WHEN 父 run 派出的批次数（含跳过批号）少于 manifest scope 所需
- THEN 派发事件行可与之对账，暴露计划偏短而非静默
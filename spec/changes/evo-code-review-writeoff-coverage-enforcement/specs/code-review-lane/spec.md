# 能力：全仓审查覆盖缺口执行层（code-review-lane）

## Requirement: 覆盖缺口终态降格与告警

全仓审查 run 收尾时，收尾守卫按既有权威口径（分片+主产物聚合，core/code_review.py covered_files/cumulative_covered_files）对 manifest scope 计算覆盖；仅在全仓核销分支（`manual_full` 或 `scheduled` 且 `window_start is None`）生效。当未覆盖文件比例严格超过阈值（固定模块常量 `CODE_REVIEW_COVERAGE_GAP_THRESHOLD = 0.02`，即 2%，非配置项）时，MUST：

1. 把该 run 的执行终态从 success 降格记为 partial：run_metrics `terminal="partial"`，`CodeReviewResult.success=False` 且 `error` 含缺口摘要（未覆盖数/总数/比例），result 对象挂 `coverage_partial=True`/`coverage_gap`；`.fenix/runs` 的 `result→done` 分类不变（执行干净结束，降格是质量终态）；
2. 经既有 `AdminStore.append({kind: SIGNAL, ...})` 告警写回通道落一条 `signal_type="code_review_coverage_gap"` 告警，正文含未覆盖文件数、比例与差集摘要（文件数过多时给计数与前若干例）；同项目同类型未处置信号已存在时不重复写；
3. 调用既有 pending-writeoff 锚写入（core/code_review.py write_pending_writeoff），锚记本 run id 与 reason=`coverage_gap`，使 core/admin_monitor.py 既有锚续审扫描自动武装 redispatch 续审。**仅非重派 run 新写锚；重派 run MUST NOT 改指锚**（链根不变量）。

边界与时序约束：

- `origin_files` 为空、manifest 缺失/损坏或覆盖判定异常时 MUST NOT 按比例降格，维持既有 WARNING/锁定；
- 同一 run 至多降格一次；幂等以同 run id 判定，异 run 的陈旧锚 MUST NOT 抑制本轮降格；
- 与重启旗标锚（maintenance_runs.py :3416）同一收尾命中时至多写一次锚，旗标锚优先；
- `coverage_gap` 锚带 `attempts`：重派 run 收尾仍超阈值时在原锚上递增（run_id 不变），达 `CODE_REVIEW_COVERAGE_GAP_MAX_RESUME = 2` 时清除该锚并升级告警「连续 N 轮续审未收敛」，停止自动续审，下一个常规周期兜底；error/restart 锚不设上限、行为不变。

未覆盖比例低于或等于阈值时 MUST 保持现行为：WARNING 留痕、success 终态、不落新锚。

## Requirement: 批次计划声明与收尾对账

分批与派子代理由 code-review agent 自主决定（core/code_review.py 无批次派发逻辑），故留痕落在 agent 计划侧。agent 在派发任何审查批次前，MUST 先把批次计划（批号 `b<N>` 与各批文件清单）写入 `.fenix/code-review/plan-<run_id>.json`；不派子代理时写单批计划或空计划（表示全自审）。run 收尾时框架 MUST 读该计划与「分片+主产物」实际覆盖对账，计划中存在但零结果行的批记为「计划缺批」并留痕（WARNING + 覆盖缺口告警正文）；计划文件缺失/损坏时留痕「无计划可对账」。该对账 MUST NOT 改变既有 success/partial 终态判定，也不改变批次执行逻辑。

## Scenario: 干净收尾但覆盖超阈值

- WHEN 全仓审查 run 无打断干净收尾、`origin_files` 非空且覆盖缺口比例严格超过 2%
- THEN run 的 run_metrics 终态记 partial、告警落账、pending-writeoff 锚（reason=coverage_gap）在册，下一轮锚续审扫描武装 redispatch 续审

## Scenario: 覆盖缺口低于或等于阈值

- WHEN 收尾覆盖缺口比例不超过 2%（含恰好 2%）
- THEN run 终态保持 success、不落新锚、无覆盖缺口信号、仅 WARNING 留痕

## Scenario: 缺口不可判

- WHEN origin_files 为空、manifest 缺失/损坏或覆盖判定异常
- THEN 维持既有 WARNING 与核销锁定，不降格、不落新锚、不发覆盖缺口信号

## Scenario: 续审连续未收敛

- WHEN coverage_gap 锚连续 2 轮续审后缺口仍超阈值
- THEN 清除该锚并升级告警「续审未收敛」，停止自动续审，等待下一个常规审查周期

## Scenario: 批次计划偏短可对账

- WHEN agent 的计划含某批（b<N>）但该批无任何分片/主产物结果行
- THEN 收尾对账留痕「计划缺批」并在覆盖缺口告警正文中可见；既有 success/partial 终态判定不变

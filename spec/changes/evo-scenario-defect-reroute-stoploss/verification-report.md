# 验证报告：evo-scenario-defect-reroute-stoploss

> ⚠️ 本报告由框架于 2026-09-18T13:44:47Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-18T13:44:47.781863+00:00

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.46M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| reroute-same-batch-stoploss-escalates | 改道重入轮（深度1）同批失败 → 提前止损升级人工：主路径用例（test_reentry_same_batch_stoploss_escalates）+ 不触碰实现轮预算用例（test_reentry_same_batch_does_not_touch_impl_budget）都通过。来源：tests/test_scenario_reroute_stoploss.py:128,151；spec scenario-defect-reroute-stoploss「改道重入后仍同批失败提前止损」 | pass | 0/2 | - |
| reroute-has-fix-continues-budget-channel | 改道重入轮有场景被修复 → 覆盖留存后继续既有改道预算通道（仍重派 judge、不升级人工）：test_reentry_has_fix_continues_budget_channel 通过。来源：tests/test_scenario_reroute_stoploss.py:163；spec「改道有进展继续预算」 | pass | 0/2 | - |
| reroute-pure-new-failures-stoploss | 改道重入轮纯新增失败场景（无一修复，改道前失败集 ⊆ 重跑失败集）→ 判同批止损：test_reentry_pure_new_failures_stoploss 通过。来源：tests/test_scenario_reroute_stoploss.py:180；design.md 边界「纯新增（无一修复）→ 按同批止损」 | pass | 0/2 | - |
| reroute-missing-corrupt-records-fail-open | 留存缺失/损坏/结构不符/空 failed_ids → 保守放行不误停（照常重派 judge）：test_missing_record_passes_fail_open、test_corrupt_record_passes_fail_open、test_struct_invalid_record_passes_fail_open、test_empty_failed_ids_record_passes_fail_open 通过。来源：tests/test_scenario_reroute_stoploss.py:197-249；design.md 回归点 5 | pass | 0/2 | - |
| reroute-round-mismatch-fail-open | 留存轮次与 _repair_depth-1 不匹配（跨链陈旧）→ 放行不误停：test_round_mismatch_record_passes_fail_open 通过。来源：tests/test_scenario_reroute_stoploss.py:251；spec「读取…轮次不匹配时 MUST 保守放行」 | pass | 0/2 | - |
| reroute-chain-head-stale-record-no-stoploss | 链首触发（深度0）+ 上一链条陈旧留存失败集相同 → 不做同批判定、照常走既有改道通道（MUST NOT 升级人工）：test_chain_head_stale_record_no_stoploss 通过。来源：tests/test_scenario_reroute_stoploss.py:266；spec「链首触发的陈旧留存不误停」 | pass | 0/2 | - |
| reroute-chain-head-writes-record-with-written-at | 跨轮失败集留存写入：链首触发写入 {round, failed_ids, written_at}（失败集跨轮可见的写入面）：test_chain_head_writes_record_with_written_at 通过。来源：tests/test_scenario_reroute_stoploss.py:284；spec「失败集跨轮可见」 | pass | 0/2 | - |
| reroute-budget-exhausted-regression | 既有预算耗尽升级路径回归：深度达上限仍走 exhausted 升级、stoploss 机制不干扰（信号保持 scenario_defect_reroute_exhausted，消息保持「预算耗尽」）：test_budget_exhausted_regression 通过。来源：tests/test_scenario_reroute_stoploss.py:299；design.md 回归点 6 | pass | 0/2 | - |
| reroute-scenario-repaired-reentry-regression | 改道后 judge 申报 scenario-repaired → 重入执行（深度1）既有通道在 stoploss 机制下不受影响：test_reroute_then_scenario_repaired_reenters_still_works 通过。来源：tests/test_scenario_reroute_stoploss.py:316；design.md「重入执行…既有通道」 | pass | 0/2 | - |
| reroute-stoploss-full-suite-green | 全量回归：tests/test_scenario_reroute_stoploss.py 全部 13 个用例通过（含既有 test_scenario_reroute_gate.py 语义不破坏的隔离验证）。来源：tests/test_scenario_reroute_stoploss.py 全文；design.md 回归测试 6 与 impl-result.json（13 个新增测试） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

- 首轮写入 10 个场景


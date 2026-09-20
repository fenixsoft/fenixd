# 验证报告：evo-self-review-result-based-classification

> ⚠️ 本报告由框架于 2026-09-17T20:56:04Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-17T20:56:04.558250+00:00

## 结论：✅ 通过（verified）

**状态：verified — 7/7 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 7/7 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.32M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| srbc-success-terminal-topic-words-stays-succeeded | 功能正向·成功终态不被正文主题词降级（spec Scenario 1/3，复现 2026-09-17 5/7 误报）：运行新增 tests/test_self_review_result_based_classification.py 的 TestSuccessTerminalWithTopicWords 分组 4 用例——parametrize 三种信号词（budget-exhausted/impl_budget_exhausted/spec_content_missing）出现在成功 result 正文，以及信号词仅位于终态邻近 3 行之外（Scenario 3 全文主题词不再降级），断言 stats[\"succeeded\"]==1、failed==0、失败样本为空。出处：tests/test_self_review_result_based_classification.py:64-121；判定口径注释 core/self_review.py:308-313 | pass | 0/6 | - |
| srbc-fallback-attribution-error-no-terminal | 异常路径·信号扫描仅兜底 error/无 result 终态（spec Scenario 2）：TestFallbackOnlyForFailureAttribution 分组 3 用例——error 终态缺省 error 文本时全文件扫描补 signal=<词> 归因（detail=signal=impl_budget_exhausted）、error 终态已有 detail 时以 _classify_run 为准不被覆盖、无 result 终态（running）+ 信号词兜底探测保留但不改写 category。出处：tests/test_self_review_result_based_classification.py:124-203；_scan_run_signals core/self_review.py:209 | pass | 0/5 | - |
| srbc-marker-real-failure-still-failed | 回归·真失败仍被捕获（spec Scenario 4）：TestMarkerRegression 用例——result 文本命中 _business_fail_marker（「SPEC 内容缺失，无法实现」）仍判 failed 且detail 以 marker= 前缀，失败样本/统计维持（既有语义回归）。出处：tests/test_self_review_result_based_classification.py:206-233；_classify_run result 分支 core/self_review.py:233 | pass | 0/3 | - |
| srbc-bucket-unchanged-no-failed-increase | 回归·无 result 终态桶位不变、failed 不因主题词增加（spec Scenario 2 AND 段 + 非目标）：TestBucketUnchangedNoFalseIncrease 分组 3 用例——running+信号词桶位不变、dropped（空文件）桶位不变、混合窗口（成功终态主题词/在飞/空文件/真失败）统计 total=4 且仅真失败计入 failed==1、失败样本仅 [impl-real-fail]。出处：tests/test_self_review_result_based_classification.py:236-286 | pass | 0/5 | - |
| srbc-signal-fallback-guardrails-regression | 回归·终态邻近 3 行信号护栏 MUST NOT 移除（spec.md 明示锁定项）：tests/test_self_review_run_semantics.py 全量 14 用例，显式断言 test_signal_fallback_when_no_marker 与 test_signal_fallback_counts_failed 两个护栏用例 PASSED（result 无 marker 时 _signal_evidence 兜底仍生效），并覆盖 error/timeout 终态语义不变。出处：tests/test_self_review_run_semantics.py:58,121；_signal_evidence core/self_review.py:193-206 | pass | 0/5 | - |
| srbc-daily-window-regression | 回归·失败样本/统计与窗口快照语义不变（design 测试策略全量回归）：tests/test_daily_self_review.py + tests/test_self_review_window_snapshot.py 全量 74 用例（失败样本、快照窗口归属、日志错误聚合语义不受本改动影响）。出处：tests/test_daily_self_review.py、tests/test_self_review_window_snapshot.py | pass | 0/2 | - |
| srbc-module-behavior-direct-verify | 功能正向·交付模块行为级端到端验证（不经 pytest，直接调用 core/self_review.py 的 collect_runs_stats/collect_failed_run_samples，构造四类 run 转录 + 空 runs 目录）：① 成功终态+正文主题词 → succeeded=1 且失败样本为空（5/7 误报修复实证）；② error 终态+信号词 → failed 且 detail=signal=impl_budget_exhausted（兜底归因）；③ 在飞 run+信号词 → running 桶位不变、failed=0（不改写 category）；④ result 命中 marker → failed(marker=...）（真失败不丢）；⑤ 空 runs 目录 → 全零桶位（空状态）。出处：core/self_review.py:271-323（collect_runs_stats/collect_failed_run_samples） | pass | 0/13 | - |

## 本轮场景集变更

当前稳定场景集共 7 个（第 1 轮）。

- 首轮写入 7 个场景


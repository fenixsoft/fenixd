# 验证报告：evo-fix-self-review-marker-match-window

> ⚠️ 本报告由框架于 2026-09-24T10:04:10Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-24T10:04:10.618271+00:00

## 结论：✅ 通过（verified）

**状态：verified — 7/7 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 7/7 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 7 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.62M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-marker-window-regression-tests-pass | 窗口收敛新增回归测试全绿（spec: 失败声明窗口匹配 + 假成功抓取语义保持，tasks 2.1/2.2）——tests/test_self_review_result_based_classification.py 18 用例全部 PASSED，含中段功能词不降级回归 test_midsummary_word_succeeded_and_not_in_samples 与窗口边界成对用例 test_declaration_window_boundary[0-True]/[95-True]/[100-False]/[300-False]（用例名带参数化后缀，实跑取证）。出处：core/self_review.py:107（_MARKER_DECLARATION_WINDOW=100）、core/self_review.py:221（head=text[:窗口]） | pass | 0/9 | - |
| cli-pinned-run-semantics-tests-pass | 既有 run 语义 pinned 用例不推翻（spec: 假成功抓取语义保持 + 信号护栏语义不变）——tests/test_self_review_run_semantics.py 14 用例全部 PASSED，含信号兜底通道 test_signal_fallback_when_no_marker、假成功抓取 test_budget_exhausted_marker_failed、成功语义 test_real_success_result_run_succeeded（实跑取证）。出处：specs/self-review-marker-match-window/spec.md Requirement「假成功抓取语义保持」「信号护栏语义不变」 | pass | 0/6 | - |
| cli-archive-stats-consumer-tests-pass | 归档统计消费方回归全绿（design 兼容性论证：既有 marker 夹具声明全部位于文本开头 0 字符，前缀窗口下保持全绿）——tests/test_self_review_archive_stats.py 15 用例全部 PASSED（实跑取证）。出处：spec/changes/evo-fix-self-review-marker-match-window/design.md 兼容性论证 | pass | 0/4 | - |
| cli-marker-window-boundary-probe | 直接驱动 _business_fail_marker/_classify_run 锁窗口边界（spec: 失败声明窗口匹配）——空文本不命中 marker；「预算耗尽」位于第 690 字符（实拍量级）marker=None 且 classify=succeeded；开头「预算已耗尽，无法继续实现」仍判 failed(marker=预算已耗尽)（假成功抓取保持）；窗口边界 95（声明起于窗口内）failed vs 100（窗口外）succeeded；「SPEC 内容缺失，无法实现」开头仍 failed。出处：core/self_review.py:212-225、spec.md Scenario「开头失败声明仍降级」 | pass | 0/6 | - |
| cli-signal-guardrail-semantics-probe | 直接驱动 _classify_run 锁信号护栏语义（spec: 信号护栏语义不变）——信号词在 assistant 事件行仍经 _signal_evidence 兜底判 failed(signal=budget-exhausted)（test_signal_fallback_when_no_marker 锁定的兜底通道不收窄）；信号词仅在 result 正文中段（impl_budget_exhausted 实拍形态）不构成二次降级、计 succeeded；超长 result（10000 字符）末尾才提及词表词不降级。出处：core/self_review.py:293-300（护栏只读 lines[:-1] 事件行、result 终态正文不作信号源）、spec.md Scenario「无信息 result 的信号兜底保持」 | pass | 0/4 | - |
| cli-aggregation-real-sample-correction | 聚合层修正——2026-09-24 日报实拍样本复现（proposal 问题背景：完全成功的 run impl-fix-codefix-wipgate-defer-1790135672-a2 被误计 failed marker=预算耗尽）——临时项目构造单 run（成功 result + 摘要第 690 字符「预算耗尽发一次性 warning」形态），collect_runs_stats 计 succeeded=1 failed=0，collect_failed_run_samples 失败样本为空。出处：core/self_review.py:372（统计经 _classify_run 判定）、core/self_review.py:387（失败样本仅收 failed） | pass | 0/2 | - |
| cli-aggregation-mixed-window-daily-report | 聚合层混合窗口日报失败数修正（proposal：失败数报 2 实为 1）——误判样本（中段词成功 run）+ 真失败（开头「预算已耗尽，无法继续实现」）同窗聚合，collect_runs_stats total=2 succeeded=1 failed=1（仅真失败计入），collect_failed_run_samples 仅含真失败 run 且 detail=marker=预算已耗尽。出处：spec.md Scenario「成功摘要中段功能词不降级」「开头失败声明仍降级」 | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 7 个（第 1 轮）。

- 首轮写入 7 个场景


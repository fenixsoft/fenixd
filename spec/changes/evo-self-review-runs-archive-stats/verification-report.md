# 验证报告：evo-self-review-runs-archive-stats

> ⚠️ 本报告由框架于 2026-09-20T20:44:17Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-20T20:44:17.421948+00:00

## 结论：✅ 通过（verified）

**状态：verified — 4/4 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 4/4 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 4 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.31M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-archive-new-tests-pass | 运行新增测试文件 tests/test_self_review_archive_stats.py（15 个用例），验证归档并集统计/去重/review-排除/失败样本同源全绿 | pass | 0/7 | - |
| cli-archive-regression-pass | 运行归档统计相关回归测试文件（test_self_review_run_semantics / result_based_classification / window_snapshot），32 个用例全绿 | pass | 0/6 | - |
| cli-archive-daily-regression-exclude-env | 运行 test_daily_self_review.py 回归（排除环境性 flaky 用例 test_daily_summary_git_unavailable_degrades——该用例在 worktree 内 tmp 目录因 git 递归探测到上层工作树 .git 而意外成功，与本 SPEC 无关），66 个用例全绿 | pass | 0/3 | - |
| cli-archive-union-direct-verify | 直接调用 collect_runs_stats / collect_failed_run_samples 验证并集行为：当前+归档计数、同 run_id 去重（当前优先）、归档 review- 排除、spec-review- 保留、失败样本含归档 run | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 4 个（第 1 轮）。

- 首轮写入 4 个场景


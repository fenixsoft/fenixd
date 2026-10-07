# 验证报告：evo-add-codefix-anomaly-redispatch-budget

> ⚠️ 本报告由框架于 2026-10-07T18:18:54Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-07T18:18:54.259092+00:00+run-result@mtime1791397134290602802

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.23M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| impl-tests-anomaly-redispatch-green | 实现者自建测试文件 tests/test_codefix_anomaly_redispatch_budget.py 存在且全绿（tasks 2.1：anomaly 预算降为 1 并触顶登记待人工、mapped 保持 3、旧记录缺键兼容、复燃合档取最近形态、降档告警一次性） | pass | 0/4 | - |
| existing-codefix-tests-regression | 既有 tests/test_code_fix.py 与 tests/test_codefix_targeted_retry.py 全绿（tasks 2.2：reg_form 入档用例 + 定向重试/parse-error 熔断既有行为逐位不动——design「明确不动」条款） | pass | 0/2 | - |
| anomaly-budget-constant-and-archive-schema | 预算常量与入档 schema：core/code_fix.py 存在 ANOMALY_FAIL_RETRY_MAX=1（design 方案 2）且 FAIL_RETRY_MAX=3 不动；record_failed_batch 按 reg_form 入档 anomaly/mapped 记录并落 reg_detail 键（tasks 1.1，core/code_fix.py:623）；不传 reg_form 的既有调用点向后兼容（缺省按 mapped） | pass | 0/8 | - |
| release-budget-split-anomaly-vs-mapped | 链边界自动重派按 reg_form 分档：mapped 与缺键（旧记录按 mapped）fail_count=1 记录被 release_retryable_failed_batches 释放重派，anomaly 记录至迟第 2 次失败后不再被释放（预算 1），mapped fail_count=3 保持永久跳过（core/code_fix.py:975；spec 场景「anomaly 不再被整批重派满 3 次」「mapped 保持既有预算」「旧失败记录向后兼容」） | pass | 0/6 | - |
| reignition-merge-latest-reg-form | 同条目集复燃合档：record_failed_batch 同条目集（乱序）再次入档沿用既有合档语义（fail_count 递增、不追加重复记录），reg_form 以最近一次失败为准——先 anomaly 后 mapped 记 mapped，先 mapped 后 anomaly 记 anomaly（core/code_fix.py:623 合档分支；spec 场景「复燃合档以最近失败形态为准」） | pass | 0/7 | - |
| anomaly-derate-alert-via-existing-channel | anomaly 降档/停派告警复用既有 write_regression_failed_alert 通道（signal_type=code_fix_regression_failed）：告警 evidence 登记 branch、tip_sha 与被跳过条目，告警文案带 reg_form；不新增告警类型（core/code_fix.py:2316，tasks 1.3；「同一失败记录生命周期内只发一次」由 impl-tests 场景的实现者自测覆盖） | pass | 0/5 | - |
| anomaly-budget-exhaustion-registers-manual-todo | anomaly 预算耗尽走既有触顶路径：.fenix/todo.md 登记「待人工排查」+被跳过条目清单，code_fix_retry_budget_exhausted 告警恰好 1 条（一次性，后续再失败不再新增），signal_type 不新增（core/code_fix.py:688 hit_max 分支、:2584 触顶告警、:1285 todo 登记；spec 场景「预算耗尽后登记待人工排查并跳过条目」） | pass | 0/6 | - |
| mapped-budget-full-lifecycle-unchanged | mapped 形态预算保持 FAIL_RETRY_MAX=3 全生命周期回归：fail_count=1/2 入档不触顶（无告警、无 todo 登记）、第 3 次入档触发一次性告警 + todo 登记、release_retryable_failed_batches 不再释放（core/code_fix.py:87/:688/:975；spec 场景「mapped 形态失败批保持既有预算」） | pass | 0/7 | - |

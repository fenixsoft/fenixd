# 验证报告：evo-self-review-timeseries-assertion-backsource

> ⚠️ 本报告由框架于 2026-10-30T13:03:02Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T13:03:01.234705+00:00+run-result@mtime1793365381332291689

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.20M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| ts-clause-present-and-renumbered | 模板落位正向：agents/self-review.md「含调查评估」清单含第 4 项粗体条款「时序聚合断言回源」，既有「归因证据边界」条款未被挤掉，原第 4 项「组织顺序」顺延为第 5 项，且各关键词恰出现一行（无重复插入）（tasks.md 1.1；agents/self-review.md:24-26） | pass | 0/11 | - |
| ts-clause-semantics-backsource-fallback | 条款语义逐字覆盖 spec 三个行为 requirement：回源触发面（连续/上行/回落/钉值/下界/合计）、回源对象两路（当晚原始汇总行 run_metrics/延迟汇总行 与 归档档案重算）、断言句同附每晚原始数字与口径（整晚总量 vs 单车道分量）、转引前轮数字必须重新回源、无法回源时降级定性或标注「未核实」（specs/self-review-timeseries-discipline/spec.md R1/R2/R3；agents/self-review.md:25） | pass | 0/12 | - |
| ts-contract-test-full-pass | 契约测试全过：tests/test_self_review_timeseries_discipline.py 在场且 7 用例全过——逐字标题在场、粗体条款头、同区并列、编号连续、语义覆盖（tasks.md 2.1；tests/test_self_review_timeseries_discipline.py:56-125） | pass | 0/10 | - |
| ts-guard-blocks-timeseries-clause-loss | 契约守护正向（spec S4.2）：静默删除「时序聚合断言回源」条款后契约测试必失败（scratch 树实测输出 6 failed, 1 passed、exit 1），恢复模板后复归 7 passed——含操作前基线在场、删除后中间态、恢复后回归对比三段（tests/test_self_review_timeseries_discipline.py:65-69） | pass | 0/12 | - |
| ts-guard-blocks-attribution-clause-loss | 契约守护双向：静默删除既有「归因证据边界」条款同样被契约测试拦截（scratch 树实测 5 failed, 2 passed、exit 1），恢复模板后复归 7 passed（tests/test_self_review_timeseries_discipline.py:59-63） | pass | 0/12 | - |
| ts-guard-blocks-title-variant-swap | 守护语序/缩略变体（tasks.md 2.1 禁止缩略「时序聚合回源」）：把条款标题整体替换为缩略变体后逐字关键词失配，契约测试失败（scratch 树实测 5 failed, 2 passed、exit 1），恢复模板后复归 7 passed（tests/test_self_review_timeseries_discipline.py:25-28 关键词逐字契约） | pass | 0/14 | - |
| ts-link-regression-self-review-prompt | 链路回归（tasks.md 1.2，只跑测试不改代码）：模板扩写不破坏既有 self_review prompt 契约用例与模板渲染用例——TestIndependentBuildPathsContainContract::test_self_review_prompt_has_contract 与 TestSelfReviewPromptEntries 两例共 3 passed（tests/test_agent_noninteractive_contract.py:121-127；tests/test_daily_self_review.py:1480-1512） | pass | 0/5 | - |
| ts-prompt-render-chain-carries-clause | 渲染链路正向：真实 PromptBuilder._build_self_review_prompt 从 AGENT_PROMPT_DIR（FRAMEWORK_ROOT/agents）加载模板并单趟填充后，两类纪律条款标题与关键语义串真实进入自省 prompt——「模板在场」推进为「链路输出在场」（core/agent_runner/prompt_builder.py:30、441-456、1993-1996） | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 8 个（第 1 轮）。

- 首轮写入 8 个场景


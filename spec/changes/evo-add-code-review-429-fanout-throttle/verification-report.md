# 验证报告：evo-add-code-review-429-fanout-throttle

> ⚠️ 本报告由框架于 2026-11-27T09:28:51Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-27T09:28:45.444551+00:00+run-result@mtime1795771730514387445

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | N/A |
| 本链增量 Token（输出） | N/A |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| cli-default-concurrency-two | 未配置项目全仓审查并发读器缺省为 2，显式配置原样生效（1.1 读器降档） | pass | 0/2 | - |
| cli-prompt-default-two-and-memory-clause | 真实 PromptBuilder 按缺省渲染扇出上限 2，且 agents/code-review.md 的 run 内 429 记忆条款随提示词注入 | pass | 0/2 | - |
| cli-run-folds-to-one-after-prior-429 | 上一轮同车道归档 jsonl 存在 3 条 429 终态子代理死亡时，新一轮 run 注入扇出上限折减至 1（2.1 跨 run 记忆） | pass | 0/2 | - |
| cli-run-keeps-two-without-prior-429 | 上一轮无 429 记录时按配置缺省 2 注入，且只认最近一份归档 run | pass | 0/2 | - |
| cli-alert-below-threshold-silent | 本 run 仅 2 条 429 子代理死亡（低于阈值 3）时不产生升级告警（3.1） | pass | 0/2 | - |
| cli-alert-three-deaths-single-write | 重现 11-24 形态（b2/b3 首发 + b2 重派，共 3 条 429 终态）时收尾直写单条升级告警，dedup_key 含 run id 且同 run 幂等（3.1） | pass | 0/2 | - |
| cli-scan-exception-fail-open | 归档缺失/扫描异常/本 run 转录不可读时一律 fail-open（按原配置值派发、不写告警、不抛异常） | pass | 0/2 | - |
| cli-default-same-source-surfaces | 缺省同源面一致：模板示例值=读器缺省 2、设置页常量=2，且审查/修复两份契约均含 run 内 429 记忆条款（1.2/1.3/1.4/2.2/2.3） | pass | 0/2 | - |
| cli-code-review-suite-passes | code-review 车道测试文件全量通过（含新增用例，无回归） | pass | 0/1 | - |

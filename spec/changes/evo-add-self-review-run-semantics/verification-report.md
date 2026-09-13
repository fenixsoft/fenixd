# 验证报告：evo-add-self-review-run-semantics

> ⚠️ 本报告由框架于 2026-09-13T07:44:50Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 21/21 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 21/21 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 21 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 6.93M |
| 本链增量 Token（输出） | 0.11M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| blind-run-marker-failed | 盲派 run 计为失败：result 文本含『SPEC 内容缺失，无法实现』时 _classify_run 判 failed（marker 命中）。出处：core/self_review.py:248-250 | pass | 0/3 | - |
| real-success-run-succeeded | 真实成功 run 不受影响：result 文本为正常收尾且无业务失败标记时照常计 succeeded。出处：core/self_review.py:254 | pass | 0/3 | - |
| budget-exhausted-marker-failed | 预算耗尽标记命中：result 文本含『预算已耗尽』时判 failed（marker 摘要含预算）。出处：core/self_review.py:248-250 + _BUSINESS_FAIL_PATTERNS:68-76 | pass | 0/3 | - |
| signal-fallback-no-marker | 双源交叉护栏-信号兜底：result 文本无标记但事件序列含 budget-exhausted 类信号时判 failed（signal 摘要）。出处：core/self_review.py:251-253 + _BUSINESS_FAIL_SIGNALS:79-85 | pass | 0/3 | - |
| empty-run-dropped | 空产物 run 计为 dropped：无任何事件行时 _classify_run 判 dropped。出处：core/self_review.py:239-240 | pass | 0/3 | - |
| marker-list-invariants | 标记清单覆盖 spec 要求的全部不变量短语（SPEC 内容缺失/无法实现/预算耗尽/零交付/零产出）。出处：_BUSINESS_FAIL_PATTERNS:68-76 | pass | 0/6 | - |
| marker-wins-without-signal | 保守路径：result 文本含标记但无结构性信号时仍按文本判 failed（marker 优先于信号）。出处：core/self_review.py:248-250 | pass | 0/3 | - |
| midfile-signal-full-scan | 全文件信号扫描兜底：信号事件落在文件中部（尾部行不覆盖）时 collect_runs_stats 仍判 failed。出处：core/self_review.py:299-304 + _scan_run_signals:207-224 | pass | 0/4 | - |
| collect-runs-stats-aggregation | 统计聚合口径：混合 fixture（标记失败/真实成功/空文件）下 collect_runs_stats 计数正确（failed/succeeded/dropped）。出处：core/self_review.py:265-307 | pass | 0/5 | - |
| failed-samples-traceability | 失败样本可追溯：collect_failed_run_samples 输出含 run_id + 命中标记/信号摘要，成功 run 不入选。出处：core/self_review.py:310-349 | pass | 0/5 | - |
| samples-sorted-and-limited | 失败样本排序与截断：多个失败 run 时样本按 run_id 倒序且受 limit 截断。出处：core/self_review.py:348-349 | pass | 0/5 | - |
| review-prefix-excluded | review- 自省 run 排除：统计与样本均跳过 review- 前缀 run。出处：core/self_review.py:288,330 | pass | 0/4 | - |
| error-terminal-regression | error 终态路径回归：error 终态（非超时/非秒挂）仍判 failed，不受业务失败语义改动影响。出处：core/self_review.py:255-262 | pass | 0/3 | - |
| timeout-terminal-regression | timeout 终态路径回归：error 文本含超时信号仍判 timeout。出处：core/self_review.py:258-259 | pass | 0/2 | - |
| instant-hang-regression | 秒挂（instant-hang）路径回归：error 文本命中秒挂签名仍判 instant_hang。出处：core/self_review.py:260-261 | pass | 0/2 | - |
| running-no-terminal | 无终态 run 计为 running：有事件但无 result/error 终态时判 running。出处：core/self_review.py:241-243,255-256 | pass | 0/2 | - |
| zero-delivery-marker-failed | 零交付标记命中：result 文本含『零交付』时判 failed。出处：core/self_review.py:248-250 + _BUSINESS_FAIL_PATTERNS:68-76 | pass | 0/3 | - |
| zero-output-marker-failed | 零产出标记命中：result 文本含『零产出』时判 failed。出处：core/self_review.py:248-250 + _BUSINESS_FAIL_PATTERNS:68-76 | pass | 0/3 | - |
| cannot-implement-marker-failed | 无法实现标记命中：result 文本含『无法实现』时判 failed。出处：core/self_review.py:248-250 + _BUSINESS_FAIL_PATTERNS:68-76 | pass | 0/3 | - |
| no-title-terminal-regression | 未知终态类型回归：type 非 result/error 时判 running（既有路径不受业务失败语义改动影响）。出处：core/self_review.py:255-256 | pass | 0/2 | - |
| signal-no-result-terminal | 信号 + error 终态回归：事件序列含 budget-exhausted 信号且终态 error（非超时/秒挂）→ failed（回归路径不受影响）。出处：core/self_review.py:255-262 | pass | 0/2 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。


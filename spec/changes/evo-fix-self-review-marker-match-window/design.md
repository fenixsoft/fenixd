# Design: 自省失败 marker 匹配窗口收敛

## 现状与关键事实

- core/self_review.py:204-213 _business_fail_marker：对传入文本做 _BUSINESS_FAIL_PATTERNS（:91-99）裸子串匹配，命中即返回词；唯一调用点 :277（_classify_run 的 type=result 分支），:278-279 命中即 return ("failed", "marker=<词>")。
- 词表含「预算耗尽」（:95）、「预算已耗尽」（:96）等功能治理词汇，与 runner 层预算文案同形。
- 既有 marker 夹具的声明全部位于文本开头且不超过 30 字符（test_self_review_run_semantics.py:35/54/73、test_self_review_result_based_classification.py:213/222/274；评审补查：test_self_review_archive_stats.py:68/100/144/220/232/242/257 亦全为开头 0 字符夹具——其余聚合消费方 test_self_review_window_snapshot.py 与 test_daily_self_review.py 不含 marker 夹具），前缀窗口下保持全绿。
- 已知两次误判样本的命中位置均在文本中段：302/711（自省 run 自身）与 692/1382（本次实拍）。

## 设计

1. 模块级常量 _MARKER_DECLARATION_WINDOW = 100；_business_fail_marker 改为在 text[:100] 内做子串匹配（命中位置自然落在窗口内），词表与返回值形态不变。
2. _classify_run / collect_runs_stats / collect_failed_run_samples 主体结构不变——失败计数与失败样本列表随之自然修正。（修订 2026-09-24 code-review，与实现对齐：_classify_run 的 result 分支同步收窄信号护栏为 `_signal_evidence(lines[:-1])`，排除 result 终态自身——_BUSINESS_FAIL_SIGNALS 与 _BUSINESS_FAIL_PATTERNS 共享「预算耗尽」词形，仅收 marker 窗口时同一次 09-24 实拍误判仍会经 signal 路径对终态行二次翻转。）
3. _signal_evidence（:216-229）函数本体与 _scan_run_signals（:232-253）不动；_signal_evidence 的护栏调用点收窄为 lines[:-1]（见上条修订），事件行兜底通道保持——信号词位于 assistant 等事件行时仍兜底判 failed（test_signal_fallback_when_no_marker 语义保持）。

## 兼容性论证

- 全部既有 marker 夹具声明位于开头 30 字符内，前缀窗口下保持全绿（2.3 语义 pin 不松动）。
- 残余敞口（修订 2026-09-24 code-review，与实现对齐）：「先长篇总结、末尾才声明失败」的假成功会漏报。接受项边界：结构性失败信号词（budget-exhausted / impl_budget_exhausted / spec_content_missing）仅出现在 result 终态行时已无检测路径——正文落在 100 字符 marker 窗口之外不再按 marker 捕获，result 终态自身（正文及该行其余字段）亦被排除出信号扫描（原先 lines 全量扫描可捕获），仅信号词位于终态邻近事件行（lines[:-1]）时仍兜底。此 fail-open 敞口为接受项（实证上失败 run 通常伴随 error 终态或事件行信号，该形态频率低），由后续 SPEC 再收敛。
- 窗口取 100 而非更小：容纳「收工自检未通过：」类前缀+声明的组合形态，同时把已知全部误判样本（692/1382 等）排除在外。

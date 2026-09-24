# Design: 自省失败 marker 匹配窗口收敛

## 现状与关键事实

- core/self_review.py:204-213 _business_fail_marker：对传入文本做 _BUSINESS_FAIL_PATTERNS（:91-99）裸子串匹配，命中即返回词；唯一调用点 :277（_classify_run 的 type=result 分支），:278-279 命中即 return ("failed", "marker=<词>")。
- 词表含「预算耗尽」（:95）、「预算已耗尽」（:96）等功能治理词汇，与 runner 层预算文案同形。
- 既有 marker 夹具的声明全部位于文本开头且不超过 30 字符（test_self_review_run_semantics.py:35/54/73、test_self_review_result_based_classification.py:213/222/274；评审补查：test_self_review_archive_stats.py:68/100/144/220/232/242/257 亦全为开头 0 字符夹具——其余聚合消费方 test_self_review_window_snapshot.py 与 test_daily_self_review.py 不含 marker 夹具），前缀窗口下保持全绿。
- 已知两次误判样本的命中位置均在文本中段：302/711（自省 run 自身）与 692/1382（本次实拍）。

## 设计

1. 模块级常量 _MARKER_DECLARATION_WINDOW = 100；_business_fail_marker 改为在 text[:100] 内做子串匹配（命中位置自然落在窗口内），词表与返回值形态不变。
2. _classify_run / collect_runs_stats / collect_failed_run_samples 结构零改动——失败计数与失败样本列表随之自然修正。
3. _signal_evidence（:216-229）与 _scan_run_signals（:232-253）不动。

## 兼容性论证

- 全部既有 marker 夹具声明位于开头 30 字符内，前缀窗口下保持全绿（2.3 语义 pin 不松动）。
- 残余敞口：未来出现「先长篇总结、末尾才声明失败」的假成功会漏报——此类 run 通常伴随 error 终态（runner 层截断）或终态邻近 3 行结构信号兜底，敞口小且可由后续 SPEC 再收敛。
- 窗口取 100 而非更小：容纳「收工自检未通过：」类前缀+声明的组合形态，同时把已知全部误判样本（692/1382 等）排除在外。

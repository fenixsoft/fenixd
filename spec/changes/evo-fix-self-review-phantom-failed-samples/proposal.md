## Why

2026-09-25 凌晨日汇总把 2 个实际成功的 run（impl / planner-plan-evo-fix-self-review-marker-match-window）误报为失败：触发词只出现在 result 正文（全文件按行计 41/22 行），被 daemon 驻留的旧版全文匹配分类器翻转。核查进一步发现当日已合回的修复（698a9a0d）只修了一半：marker 声明窗口已收窄到前 100 字符，但信号护栏 _signal_evidence(lines[:-1]) 只排除 result 终态行，不排除其直接前驱的 assistant 副本行——result 文本正是该 assistant 消息的副本，正文失败词必然同时出现在副本行，从信号路径原路回流。用当前代码直接驱动这两个 run 仍输出 failed（signal=预算耗尽 / signal=budget-exhausted），即重启 daemon 也无法消除该误报；任何收工摘要正文提及这些业务失败词的 run（恰是修此类问题的 run）都会持续被计为失败并污染每日自省输入。

## What Changes

- 信号护栏补齐：_classify_run 的信号证据扫描排除与 result 终态文本同源的前驱行（尾三行 [assistant, run_metrics, result] 结构中的 assistant 副本行），使仅存在于 result 正文及其副本中的失败词不构成 failed 证据。
- 双源交叉守卫：聚合侧（collect_failed_run_samples / collect_runs_stats）在样本分类为 failed 时比对 daemon 侧 run_metrics 的 terminal 字段（数据源 fenixd.log 的 run_metrics 日志行，读侧复用现成 metric 索引）：terminal=success 而分类为 failed 时不计入失败统计与失败样本，改写 signal_type=self_review_phantom_failure 的告警（warning、不自动 mark_handled）；metric 索引查不到终态时维持现状计入，不因缺数据改判。

## Impact

- 影响：core/self_review.py（信号护栏 + 聚合交叉守卫）、core/dashboard/data/runs.py（metric 索引公共访问器）、core/admin_monitor.py（SelfReviewScheduler 构造点注入 AdminStore 接线）、tests/test_self_review_terminal_crosscheck.py（新单测）。
- 不改变 marker 声明窗口与真实失败检出语义；终态之外的独立失败证据仍可检出；索引缺失的样本宁可不拦不可误伤。
- 告警走既有 AdminStore/.fenix/admin_alerts.json 通道，不新增存储。
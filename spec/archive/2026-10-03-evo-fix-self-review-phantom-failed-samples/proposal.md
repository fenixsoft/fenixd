## Why

2026-09-25 凌晨日汇总把 2 个实际成功的 run（impl / planner-plan-evo-fix-self-review-marker-match-window）误报为失败：触发词只出现在 result 正文（全文件按行计 41/22 行），被 daemon 驻留的旧版全文匹配分类器翻转。核查进一步发现当日已合回的修复（698a9a0d）只修了一半：marker 声明窗口已收窄到前 100 字符，但信号护栏 _signal_evidence(lines[:-1]) 只排除 result 终态行，不排除其直接前驱的 assistant 副本行——result 文本正是该 assistant 消息的副本，正文失败词必然同时出现在副本行，从信号路径原路回流。用当前代码直接驱动这两个 run 仍输出 failed（signal=预算耗尽 / signal=budget-exhausted），即重启 daemon 也无法消除该误报；任何收工摘要正文提及这些业务失败词的 run（恰是修此类问题的 run）都会持续被计为失败并污染每日自省输入。

## What Changes

- 信号护栏补齐：_classify_run 的信号证据扫描排除终态邻近窗口（尾三行 [assistant, run_metrics, result] 结构）中的 assistant 事件行——该行承载与 result 终态摘要同源的收工叙事回声（实测两幻影 run 的失败词均在 assistant 行，但不逐字等于 result 全文，故排除按行结构识别、不做逐字副本匹配），使仅存在于 result 正文及其回声行中的失败词不构成 failed 证据。
- 双源交叉守卫：聚合侧（collect_failed_run_samples / collect_runs_stats）仅对信号路径命中（detail 前缀 signal=）的 failed 分类比对 daemon 侧 run_metrics 的 terminal 字段（数据源 fenixd.log 的 run_metrics 日志行，读侧复用现成 metric 索引）：terminal=success 而分类为 failed 时不计入失败统计与失败样本，改写 signal_type=self_review_phantom_failure 的告警（warning、不自动 mark_handled）；marker= 命中（D1 假成功抓取：进程正常收尾即记 terminal=success，runner.py:3313，与 result 文本内容无关）是既定真实失败检出，MUST NOT 纳入守卫；metric 索引查不到终态时维持现状计入，不因缺数据改判。

## Impact

- 影响：core/self_review.py（信号护栏 + 聚合交叉守卫）、core/dashboard/data/runs.py（metric 索引公共访问器）、tests/test_self_review_terminal_crosscheck.py（新单测）、tests/test_self_review_run_semantics.py 与 tests/test_self_review_result_based_classification.py（更新锁旧信号语义的既有夹具，见 tasks 1.3）。AdminStore 注入接线已存在（core/admin_monitor.py:959 构造 SelfReviewScheduler 时已传 store=self.store），admin_monitor.py 无需改动。
- 不改变 marker 声明窗口与真实失败检出语义；终态之外的独立失败证据仍可检出；索引缺失的样本宁可不拦不可误伤。
- 告警走既有 AdminStore/.fenix/admin_alerts.json 通道，不新增存储。
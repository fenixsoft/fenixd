## Context

- 分类器现状：core/self_review.py:107 _MARKER_DECLARATION_WINDOW=100、:212-225 _business_fail_marker 只扫声明区（698a9a0d 已修复）；:301-303 信号护栏 _signal_evidence(lines[:-1]) 只排除 result 终态行；_read_run_tail 取尾 3 行，结构为 [assistant, run_metrics, result]，assistant 行是 result 文本的副本。
- 实测复现：用当前工作区代码驱动 .fenix/runs/archive/impl-evo-fix-self-review-marker-match-window-1790242754-a1.jsonl 与 planner-plan-…-1790243612-a1.jsonl，均输出 failed（signal=预算耗尽 / signal=budget-exhausted）——impl 的 assistant 行含收工摘要正文（偏移 739 处「预算耗尽」），planner 的 assistant 行含测试场景表原文。
- 终态数据源：daemon 收尾写 fenixd.log 的 run_metrics 行（core/agent_runner/runner.py:5249 _log_run_metrics，context 含 terminal）；读侧索引 _load_run_metric_index（core/dashboard/data/runs.py:46，含轮转处理）+ _strip_run_attempt_suffix（:28）对齐 -a1/-r1 后缀。
- 聚合入口：collect_daily_summary（core/self_review.py:693）→ collect_runs_stats（:338）/ collect_failed_run_samples（:391）；SelfReviewScheduler 由 AdminMonitor 懒构造（core/admin_monitor.py:951-953），告警可经注入 AdminStore 落 .fenix/admin_alerts.json。
- 幻影案例：日汇总转录（入队 2026-09-24T18:03:44Z）51 总/48 成功/2 失败，两条失败样本均幻影；daemon 侧 fenixd.log:20712/20833 记录 terminal=success。

## Goals / Non-Goals

- Goals：成功 run 不再因正文提及失败词被计失败；即使分类器仍有漏网，聚合侧双源交叉守卫把幻影拦成告警而非失真统计。
- Non-Goals：不重写分类器词表；不动 daemon 侧 run_metrics 写入格式；不对已出窗的历史样本做追溯。

## Risks / Trade-offs

- 排除 assistant 副本行可能漏掉「只在 assistant 行出现」的真实失败证据：此类失败通常同时体现为 subtype!=success / is_error=True 或声明区 marker 命中，信号路径仅是兜底，可接受。
- 交叉守卫依赖 fenixd.log 在场：跨轮转旧 run 需回退 .fenixd.log.1；再往外查不到时按「索引缺失维持现状」处理，宁可不拦不可误伤真实失败样本。
- 告警噪音：守卫触发即意味着分类器仍有意料外误报，warning + 不自动 handled 保证人工可见；聚合每日至多一轮，频度天然受控。

## Migration Plan

1. 落地信号护栏补齐 + 单测（用两个幻影 run 的真实尾三行形态做夹具）。
2. 落地聚合交叉守卫 + AdminStore 接线。
3. 次日核对日汇总：失败样本应只剩真实失败；若 self_review_phantom_failure 告警出现，按告警 detail 继续收口分类器。

## Open Questions

- 守卫是否应同时覆盖 future 其他聚合口径（如周汇总）：暂只做日汇总同路径，观察后再议。
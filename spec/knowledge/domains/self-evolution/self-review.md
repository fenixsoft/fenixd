<!-- knowledge: capability=self-review rev=5 sources=spec/archive/2026-09-22-evo-self-review-result-based-classification,spec/archive/2026-09-25-evo-self-review-runs-archive-stats,spec/archive/2026-10-03-evo-fix-self-review-phantom-failed-samples,spec/archive/2026-10-06-fix-run-cleanup-attach-spec-archive,spec/archive/2026-10-30-evo-fix-self-review-phantom-running -->

# 自省聚合口径（run 统计与失败判定）

每日自省对窗口内 run 的成败判定、失败归因与计数来源口径：成败以 run 终态为准，统计源覆盖已归档 run。

## 现行规则

- 成败判定以 run 终态为准：`_classify_run` 返回 `succeeded`（终态为 result、result 文本未命中业务失败标记 `_business_fail_marker`、且剥除回声行后的终态邻近事件序列未命中 `_signal_evidence` 信号）的 run 计为成功；聚合层不得再对这类 run 执行全文件信号词子串扫描（`_scan_run_signals`）并据以降级为 failed。成功判定的权威来源是 `_classify_run` 的 result 分支结果本身，不设「成功语义文本白名单」之类的附加文本匹配层——「已退出」这类朴素文本同样计为成功。
- 转录正文（含文件中部事件）出现预算耗尽/内容缺失等主题词，对已有 result 成功终态的 run 不构成失败判据——评审/修复/规划类任务正文必然讨论这些主题，据以翻转即制造误报。
- 信号判据的作用域仅限 `_classify_run` 内的终态邻近尾部 3 行事件（`_signal_evidence`，run 产物收尾结构恒为 [assistant, run_metrics, result]），用于捕获「终态 result 但实际业务失败」的情形。信号证据视图先剥除窗口内的 assistant 事件行——该行承载与 result 终态摘要同源的收工叙事回声，按行结构识别（type=assistant 即回声行）排除、不做逐字副本内容匹配；剥除后末行恒为 result 终态行，再去掉终态行自身构成最终信号视图。仅存在于 result 正文及其 assistant 回声行中的业务失败词不构成 failed 证据；信号词出现在窗口内非 assistant、非 result 的事件行（独立失败证据）时仍可命中并计 failed。
- result 正文的失败声明归 marker 声明窗口管辖：`_business_fail_marker` 只在 result 文本前缀（前 100 字符）内做子串匹配——失败声明固定位于收工摘要开头；正文中段对失败主题词的功能性复述（如成功摘要里「预算耗尽发一次性 warning」）不属于声明。
- 全文件信号扫描（`_scan_run_signals`）仅对非 succeeded 终态启用，且仅用于失败归因摘要（detail），不改写 `_classify_run` 给出的 category：error 终态用它补充失败归因，无 result 终态用它兜底探测结构性失败信号（如预算耗尽/spec 缺失）；`running`（在飞/异常残留）与 `dropped`（空文件/无事件）终态保持原分类，不因全文主题词命中被改写为 failed（在飞 run 的转录正文必然包含被修改/阅读的源码字面量）。
- 双源交叉守卫（聚合侧）：统计与失败样本通道（`collect_runs_stats` / `collect_failed_run_samples`）仅对信号路径命中（detail 前缀 `signal=`）的 failed 分类比对 daemon 侧 run_metrics 的 terminal 字段。terminal=success 而分类为 failed 即幻影失败：不计入失败统计与失败样本（统计侧改计 succeeded），并产出一条 `signal_type=self_review_phantom_failure`、severity=warning 的告警，不自动 mark_handled（AdminStore 未注入时降级 logger.warning，不落盘告警）。
- 守卫读源：daemon 收尾写 `.fenix/logs/fenixd.log` 的 run_metrics 日志行（context 含 terminal），正常 result 收尾一律记 terminal=success、与 result 文本内容无关；读侧经公共 metric 索引访问器查询，含轮转日志（`.fenixd.log.1`）回退与 `-a1`/`-r1` attempt 后缀对齐。
- marker= 命中不纳入守卫：daemon 对正常 result 收尾本就记 terminal=success，marker 命中（假成功抓取——进程正常收尾但业务声明失败）是既定真实失败检出，照常计入失败统计与失败样本，不产生幻影告警；error 终态失败同样照常计入，不查终态。
- 索引缺失不改判：metric 索引中查不到该 run 的终态记录（如日志已轮转出窗）时维持现状计入失败，宁可不拦不可误伤真实失败样本，不因缺数据改判。
- 真失败不丢：result 文本命中业务失败标记、或终态为 error 的 run 维持 failed 分类，失败样本与统计不变。
- 统计源为并集：`collect_runs_stats` 的统计源 = `.fenix/runs/` 当前目录 `*.jsonl` ∪ 归档目录 `*.jsonl`（归档目录缺失时退化为仅当前目录）——终态 run 即时移入归档后仍计入窗口统计，摘要数字与归档实际一致。
- 窗口归属按 run_id 内嵌开始时间戳判定（缺失回退文件 mtime），复用既有辅助函数；同一并集口径覆盖失败样本通道 `collect_failed_run_samples`——计数与样本同源，不得计数含归档而样本只看当前目录。
- 保持排除 `review-` 前缀（自省自身 run；区别于 spec-review-/code-review- 前缀）；只读遍历、不触发写操作；counts 键为 total/succeeded/failed/instant_hang/timeout/dropped/running/superseded/ended/stale（其中 superseded/ended/stale 三桶的分类与对账口径见 [phantom-running-guard](phantom-running-guard.md)），不含成本字段（成本归因由 `.fenix/cost/` 独立类目承担）。
- 边界：不改变归档时机与产物清理时机（早于窗口且已被清理的 run 不回溯可见）；不改变 `_classify_run` 的失败/超时/秒挂分类语义。

## 溯源

- 2026-09-22 evo-self-review-result-based-classification（spec/archive/2026-09-22-evo-self-review-result-based-classification） — 失败判定定为以 run 终态为准，废除聚合层对成功终态的全文件信号词降级；信号扫描限非成功终态且仅作归因摘要（治「失败 7 中 5 个误报」）
- 2026-09-25 evo-self-review-runs-archive-stats（spec/archive/2026-09-25-evo-self-review-runs-archive-stats） — 统计源扩为当前目录 ∪ 归档目录并集，窗口归属按 run_id 内嵌时间戳，失败样本通道同源对齐（治「窗口内完成 run 归档即消失、摘要总 run 数失真」）
- 2026-10-03 evo-fix-self-review-phantom-failed-samples（spec/archive/2026-10-03-evo-fix-self-review-phantom-failed-samples） — 信号证据剥除终态邻近窗口内的 assistant 收工叙事回声行，成功 run 正文提及失败词不再被判失败；聚合侧新增与 daemon run_metrics 终态的双源交叉守卫，漏网幻影改计成功并出 self_review_phantom_failure 告警（marker 命中与索引缺失维持原判）
- 2026-10-06 fix-run-cleanup-attach-spec-archive（spec/archive/2026-10-06-fix-run-cleanup-attach-spec-archive） — 摘除本页对 runs.keep=50 保留口径的引用（该配置已取消），统计并集与边界语义不变
- 2026-10-30 evo-fix-self-review-phantom-running（spec/archive/2026-10-30-evo-fix-self-review-phantom-running） — counts 键清单扩为含 superseded/ended/stale 十键（旧七键清单作废），三桶分类与对账细节移交 phantom-running-guard 页承载

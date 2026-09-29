<!-- knowledge: capability=self-review rev=2 sources=spec/archive/2026-09-22-evo-self-review-result-based-classification,spec/archive/2026-09-25-evo-self-review-runs-archive-stats -->

# 自省聚合口径（run 统计与失败判定）

每日自省对窗口内 run 的成败判定、失败归因与计数来源口径：成败以 run 终态为准，统计源覆盖已归档 run。

## 现行规则

- 成败判定以 run 终态为准：`_classify_run` 返回 `succeeded`（终态为 result、result 文本未命中业务失败标记 `_business_fail_marker`、且终态邻近事件序列未命中 `_signal_evidence` 信号）的 run 计为成功；聚合层不得再对这类 run 执行全文件信号词子串扫描（`_scan_run_signals`）并据以降级为 failed。成功判定的权威来源是 `_classify_run` 的 result 分支结果本身，不设「成功语义文本白名单」之类的附加文本匹配层——「已退出」这类朴素文本同样计为成功。
- 转录正文（含文件中部事件）出现预算耗尽/内容缺失等主题词，对已有 result 成功终态的 run 不构成失败判据——评审/修复/规划类任务正文必然讨论这些主题，据以翻转即制造误报。
- 信号判据的作用域仅限 `_classify_run` 内的终态邻近尾部 3 行事件（`_signal_evidence`），用于捕获「终态 result 但实际业务失败」的情形。
- 全文件信号扫描（`_scan_run_signals`）仅对非 succeeded 终态启用，且仅用于失败归因摘要（detail），不改写 `_classify_run` 给出的 category：error 终态用它补充失败归因，无 result 终态用它兜底探测结构性失败信号（如预算耗尽/spec 缺失）；`running`（在飞/异常残留）与 `dropped`（空文件/无事件）终态保持原分类，不因全文主题词命中被改写为 failed（在飞 run 的转录正文必然包含被修改/阅读的源码字面量）。
- 真失败不丢：result 文本命中业务失败标记、或终态为 error 的 run 维持 failed 分类，失败样本与统计不变。
- 统计源为并集：`collect_runs_stats` 的统计源 = `.fenix/runs/` 当前目录 `*.jsonl` ∪ 归档目录 `*.jsonl`（归档目录缺失时退化为仅当前目录）——终态 run 即时移入归档（runs.keep=50）后仍计入窗口统计，摘要数字与归档实际一致。
- 窗口归属按 run_id 内嵌开始时间戳判定（缺失回退文件 mtime），复用既有辅助函数；同一并集口径覆盖失败样本通道 `collect_failed_run_samples`——计数与样本同源，不得计数含归档而样本只看当前目录。
- 保持排除 `review-` 前缀（自省自身 run；区别于 spec-review-/code-review- 前缀）；只读遍历、不触发写操作；counts 键固定为 total/succeeded/failed/instant_hang/timeout/dropped/running，不含成本字段（成本归因由 `.fenix/cost/` 独立类目承担）。
- 边界：不改变归档时机与 runs.keep 阈值（早于窗口且已被清理的 run 不回溯可见）；不改变 `_classify_run` 的失败/超时/秒挂分类语义。

## 溯源

- [2026-09-22 evo-self-review-result-based-classification](spec/archive/2026-09-22-evo-self-review-result-based-classification/) — 失败判定定为以 run 终态为准，废除聚合层对成功终态的全文件信号词降级；信号扫描限非成功终态且仅作归因摘要（治「失败 7 中 5 个误报」）
- [2026-09-25 evo-self-review-runs-archive-stats](spec/archive/2026-09-25-evo-self-review-runs-archive-stats/) — 统计源扩为当前目录 ∪ 归档目录并集，窗口归属按 run_id 内嵌时间戳，失败样本通道同源对齐（治「窗口内完成 run 归档即消失、摘要总 run 数失真」）

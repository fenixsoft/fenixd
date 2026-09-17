# Spec Delta: self-review

## MODIFIED Requirements

### Requirement: 自省失败判定以 run 终态为准

每日自省聚合（`collect_runs_stats` 与 `collect_failed_run_samples`）MUST 以 run 的终态语义判定成败：当 `_classify_run` 返回 `succeeded`（终态为 result，result 文本未命中 `_business_fail_marker`，且终态邻近事件序列未命中 `_signal_evidence` 信号）时，MUST 视为成功，MUST NOT 在聚合层再执行全文件信号词子串扫描（`_scan_run_signals`）并据此降级为 failed。

判定 `succeeded` 的权威来源 MUST 为 `_classify_run` 的 result 分支判定结果本身，MUST NOT 引入「成功语义文本白名单」之类的额外文本匹配层：result 终态只要未命中 marker 与终态邻近信号词即为 succeeded，无论其文本形态（「已退出」这类朴素文本同样计为 succeeded）。

对已有 result 成功终态的 run，转录正文（含文件中部事件）中出现预算耗尽/内容缺失等主题词 MUST NOT 构成失败判据。**信号判据的作用域仅限** `_classify_run` 内的 `_signal_evidence`（终态邻近尾部 3 行事件，core/self_review.py:193-206、:253-255），该邻近判定 MUST NOT 被移除——它是「终态 result 但实际业务失败」的既有护栏，且被 tests/test_self_review_run_semantics.py::test_signal_fallback_when_no_marker 与 ::test_signal_fallback_counts_failed 锁定。

信号扫描（`_scan_run_signals`，全文件）MUST 仅对非 succeeded 终态启用，且**仅用于失败归因摘要（detail），MUST NOT 改变 `_classify_run` 给出的 category**：error 终态（作为失败归因补充）或无 result 终态（兜底探测结构性失败信号，如预算耗尽/spec 缺失）。特别是 `running`（在飞/异常残留）与 `dropped`（空文件/无事件）终态 MUST 保持原分类，MUST NOT 因全文件主题词命中被改写为 failed——在飞 run 的转录正文必然包含被修改/阅读的源码字面量（如 core/self_review.py 内的「预算耗尽」「impl_budget_exhausted」），改写会制造与本次修复同源的新误报。

**背景（实测依据）**：2026-09-17 自省「失败 7」中 5 个误报 run（repair-refactor-verification-module-1789572248-a1 / repair-refactor-agent-runner-module-1789521012-a1 / planner-plan-refactor-dashboard-data-module-1789501658-a1 / planner-judge-refactor-dashboard-data-module-1789502977-a1 / evo-1789496886）终态 result 均成功，但全文件命中信号词（2/9/1/1/39 次）被 `_scan_run_signals` 翻转误判；`succeeded` 分支的兜底扫描位于 core/self_review.py:310-312 与 :351-353。

上述 5 个 run 的产物文件已随 `.fenix/runs/` 轮转不在仓库内（现存 3 个 jsonl），原始证据的持久副本见 `.fenix/todo.md` 2026-09-17 节（浪费#1/可改进条目）与 `.fenix/evolution/items.jsonl`（条目 25f4ff11fa83 / 8e0ff15b7401）；同类误报的 09-16 实测（10/10 样本 `_classify_run` 返回 succeeded 而全文件扫描命中）见条目 3e42b0d064f5。

#### Scenario: 成功终态不被主题词降级

- **WHEN** 一个 run 终态为 result 且文本为成功语义（如「合并冲突已解决并提交」），但转录正文讨论过预算耗尽/spec_content_missing 等主题
- **THEN** `collect_runs_stats` 将其统计为 succeeded，`collect_failed_run_samples` 不将其列入失败样本（断言：信号词命中不改变 succeeded 分类）

#### Scenario: 信号扫描仅兜底 error/无 result 终态

- **WHEN** 一个 run 终态为 error，或无 result 终态（含被截断/空文件）
- **THEN** 信号扫描继续作为失败归因兜底执行，命中信号词给出 `signal=<词>` 归因摘要（真失败不丢）
- **AND** 该兜底仅补充 detail 摘要，不改变 `_classify_run` 给出的 category：`running`/`dropped` 在统计中仍计入原桶位（断言：为 `running`/`dropped` 的 run 构造含信号词的转录后，`stats["running"]`/`stats["dropped"]` 不变、`stats["failed"]` 不因该 run 增加）

#### Scenario: 全文主题词不再降级成功终态

- **WHEN** 一个 run 终态为 result 且命中 `succeeded`，信号词出现在终态邻近 3 行之外的正文中部
- **THEN** `collect_runs_stats` 计为 succeeded、`collect_failed_run_samples` 不列入失败样本（断言：`_scan_run_signals` 命中但 category 不变）

#### Scenario: 真失败仍被捕获

- **WHEN** run 终态 result 文本命中业务失败标记（`_business_fail_marker`）或终态为 error
- **THEN** 分类维持 failed，样本与统计不变（回归：既有 test_daily_self_review.py 失败样本断言全绿）
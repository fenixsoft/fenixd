# Spec Delta: self-review

## MODIFIED Requirements

### Requirement: 自省失败判定以 run 终态为准

每日自省聚合（`collect_runs_stats` 与 `collect_failed_run_samples`）MUST 以 run 的终态语义判定成败：当 `_classify_run` 返回 `succeeded`（终态为 result 且文本无业务失败标记/信号）时，MUST 视为成功，MUST NOT 再执行全文件信号词子串扫描并据此降级为 failed。

信号扫描（`_scan_run_signals`）MUST 仅对非 succeeded 终态启用：error 终态（作为失败归因补充）或无 result 终态（兜底探测结构性失败信号，如预算耗尽/spec 缺失）。对已有 result 成功终态的 run，正文中出现预算耗尽/内容缺失等主题词 MUST NOT 构成失败判据。

**背景（实测依据）**：2026-09-17 自省「失败 7」中 5 个误报 run（repair-refactor-verification-module-1789572248-a1 / repair-refactor-agent-runner-module-1789521012-a1 / planner-plan-refactor-dashboard-data-module-1789501658-a1 / planner-judge-refactor-dashboard-data-module-1789502977-a1 / evo-1789496886）终态 result 均成功，但全文件命中信号词（2/9/1/1/39 次）被 `_scan_run_signals` 翻转误判；`succeeded` 分支的兜底扫描位于 core/self_review.py:310-312 与 :351-353。

#### Scenario: 成功终态不被主题词降级

- **WHEN** 一个 run 终态为 result 且文本为成功语义（如「合并冲突已解决并提交」），但转录正文讨论过预算耗尽/spec_content_missing 等主题
- **THEN** `collect_runs_stats` 将其统计为 succeeded，`collect_failed_run_samples` 不将其列入失败样本（断言：信号词命中不改变 succeeded 分类）

#### Scenario: 信号扫描仅兜底 error/无 result 终态

- **WHEN** 一个 run 终态为 error，或无 result 终态（含被截断/空文件）
- **THEN** 信号扫描继续作为失败归因兜底执行，命中信号词给出 `signal=<词>` 归因摘要（真失败不丢）

#### Scenario: 真失败仍被捕获

- **WHEN** run 终态 result 文本命中业务失败标记（`_business_fail_marker`）或终态为 error
- **THEN** 分类维持 failed，样本与统计不变（回归：既有 test_daily_self_review.py 失败样本断言全绿）
# Proposal: self-review-result-based-classification

## Why

每日自省聚合（`collect_runs_stats` / `collect_failed_run_samples`，core/self_review.py:267/327）对 result 成功终态的 run 仍做全文件信号词子串扫描兜底：`_scan_run_signals`（:209）匹配 budget-exhausted / spec_content_missing / impl_budget_exhausted / 预算耗尽（`_BUSINESS_FAIL_SIGNALS` :79-84），而评审/修复/规划任务正文必然讨论这些主题（失败分类与预算熔断正是常见 SPEC 主题），导致成功 run 必误报。2026-09-17 自省「失败 7」中 5 个为误报（10/20 → 5/7 恶化），每日回顾/todo.md 系统性误导人工判断方向，每次自省需人工纠偏。

已合入的 evo-run-failure-artifact-first（9dd9fd08）只覆盖评审结果落盘层（core/pm_engine/spec_review.py），未覆盖自省统计层，互补不重复。

## What Changes

- 自省失败判定以 run 终态为准：result 成功终态（repaired/approved/success/plan-ready/conflict resolved 等成功语义文本）即 succeeded，不再被全文件信号词扫描降级。
- 信号扫描仅保留给 error 终态或无 result 终态的 run（兜底归因），真失败不丢。
- 对 repair/planner/evo 类 run 移除预算词扫描依赖（主题命中不构成失败证据）。
- 使「失败 N」统计与样本清单恢复可信。

## 非目标

- 不改变 `_classify_run` 的失败/超时/秒挂分类语义（error 侧维持）。
- 不做 .fenix-run-result.json 多层目录映射（以终态 result 文本判定为基座，草案 8c59d4a77897 同口径）。
- 不改变自省输出契约（todo.md 条目结构）。
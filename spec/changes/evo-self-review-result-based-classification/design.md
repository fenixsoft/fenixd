# Design: self-review-result-based-classification

## 背景与痛点

自省聚合对 result 成功终态仍做全文件信号词扫描（core/self_review.py:310-312、:351-353），信号词（预算耗尽/impl_budget_exhausted/spec_content_missing）与 repair/planner/evo 轮正文主题高度重合，成功 run 必误报。2026-09-16 误报 10/20，09-17 5/7，持续误导人工判断。

## 目标

- result 成功终态即 succeeded，不被信号词降级。
- 信号扫描仅兜底 error/无 result 终态，真失败不丢。
- 「失败 N」统计与样本清单恢复可信。

## 非目标

- 不动 `_classify_run` 的 error 侧语义（timeout/instant_hang/failed 不变）。
- 不做 .fenix-run-result.json 目录映射（与 evo 草稿 8c59d4a77897 的非目标一致）。

## 方案

1. `collect_runs_stats`（:310-312）与 `collect_failed_run_samples`（:351-353）：删除 `if category == "succeeded": sig = _scan_run_signals(...)` 兜底分支——succeeded 终态直接计数，不再扫描。
2. `_classify_run` 的 result 分支已含 `_signal_evidence(lines)`（尾部 3 行信号检查，:193-205），作为 result 文本未命中标记时的兜底保留；全文件扫描仅保留给 error/无终态路径（`collect_log_errors` 侧不受影响）。
3. 兜底归因保留：error 终态或无 result 终态时仍可用 `_scan_run_signals` 补充信号归因（例如「spec_content_missing」出现在 error 上下文），实现方式为在非 succeeded 分支追加扫描。
4. 回归：新增单测覆盖「主题词出现在成功终态正文 → 仍 succeeded」与「error 终态 + 信号词 → failed(signal=...)」两类。

## 测试策略

- 新文件 tests/test_self_review_result_based_classification.py：构造 run 转录夹具（成功 result + 正文含预算耗尽 / error 终态 + 信号词 / 无终态 + 信号词），断言分类与样本清单。
- 既有 tests/test_daily_self_review.py 全量回归（失败样本、窗口快照语义不变）。
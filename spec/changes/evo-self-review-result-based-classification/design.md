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

1. `collect_runs_stats`（:310-312）与 `collect_failed_run_samples`（:351-353）：删除 `if category == "succeeded": sig = _scan_run_signals(...)` 兜底分支——succeeded 终态直接计数，不再扫描。判定 `succeeded` 的口径 = `_classify_run` 的 result 分支结果本身（result 文本未命中 marker 且终态邻近 3 行未命中 `_signal_evidence`），**不引入成功语义文本白名单**：`repaired/approved/success/plan-ready/conflict resolved` 只是典型样本，朴素文本（如「已退出」）同样计为 succeeded。
2. `_classify_run` 的 result 分支已含 `_signal_evidence(lines)`（终态邻近尾部 3 行信号检查，:193-206、:253-255），作为 result 文本未命中标记时的兜底**保留，不得移除**（被 tests/test_self_review_run_semantics.py::test_signal_fallback_when_no_marker / ::test_signal_fallback_counts_failed 锁定）；全文件扫描仅保留给 error/无终态路径（`collect_log_errors` 侧不受影响）。
3. 兜底归因保留：`_scan_run_signals` 仅用于**补 detail 摘要**，且 MUST NOT 改写 `_classify_run` 给出的 category。落地口径：
   - `collect_failed_run_samples`：对 `category == "failed"` 的样本，在 `detail` 为空或需补充时可用全文件扫描拼出 `signal=<词>` 归因（`_classify_run` 已给 detail 时以前者为准）。
   - `collect_runs_stats`：无 detail 输出通道，MUST NOT 追加扫描改写 category（尤其不得把 `running`/`dropped`/`timeout`/`instant_hang` 改写为 failed）。
   - 明确禁止：「在非 succeeded 分支一律 `if sig: category = "failed"`」——该写法会把在飞 run（其转录正文必然含被修改源码的字面量，如 core/self_review.py 的「预算耗尽」「impl_budget_exhausted」）统计为失败，制造与本次修复同源的新误报，并违反「不改变 `_classify_run` 的失败/超时/秒挂分类语义」非目标。
4. 已知覆盖边界（接受项）：信号词位于终态邻近 3 行之外、且 result 文本非业务失败语义的 run，不再被翻转判失败（原先由全文件扫描捕获）。实证上该边界不影响既有护栏的真实收益：盲派空 spec 12 run 的失败凭据是 result 文本「SPEC 内容缺失，无法实现」（命中 `_business_fail_marker`，marker 路径保留），非全文件扫描（证据：.fenix/evolution/items.jsonl 条目 05f246f222ea / 14f653b46b1e）。此接受项 MUST 在实现注释中以同样口径写明。
5. 回归：新增单测覆盖「主题词出现在成功终态正文（含终态邻近 3 行之外）→ 仍 succeeded」「error 终态 + 信号词 → failed(signal=...)」「无 result 终态（running/dropped）+ 信号词 → category 不变」三类。

## 测试策略

- 新文件 tests/test_self_review_result_based_classification.py：构造 run 转录夹具（成功 result + 正文含预算耗尽 / error 终态 + 信号词 / 无终态 + 信号词），断言分类与样本清单。
- 既有 tests/test_daily_self_review.py 全量回归（失败样本、窗口快照语义不变）。
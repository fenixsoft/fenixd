## Deliverables

```yaml
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: agents/code-review.md
  kind: modify
- path: tests/test_code_review_coverage_gate.py
  kind: new
```

> 说明：`core/code_review.py` 无需修改——`write_pending_writeoff` / `covered_files` / `cumulative_covered_files` / `read_manifest_files` 均已存在，直接复用。`core/admin_monitor.py` 零改动（见 design「不改动」）。

## 1. 覆盖对账执行层

- [x] 1.1 core/agent_runner/maintenance_runs.py：给全仓审查收尾的 `_writeoff_coverage_guard` 调用段加执行层——按既有权威口径（分片+主产物，复用 `core/code_review.py` 的 `cumulative_covered_files`/`covered_files` 与 `origin_files`）计算 `gap_ratio = len(origin_files - covered) / len(origin_files)`；仅在全仓核销分支（`manual_full` 或 `scheduled` 且 `window_start is None`）生效。`gap_ratio > CODE_REVIEW_COVERAGE_GAP_THRESHOLD(0.02)` 时：（a）置 `coverage_demoted` 独立标志，**不改写 `run_ok`**；收尾 `CodeReviewResult(success=run_ok and not coverage_demoted)`，`error` 追加缺口摘要，result 对象动态挂 `coverage_partial`/`coverage_gap`；`_log_lane_run_metrics` 增可选 `terminal` 形参并传 `"partial"`；（b）经 `AdminStore.append({kind: SIGNAL, ...})` 落 `signal_type="code_review_coverage_gap"` 告警（evidence 含未覆盖数/总数/比例/示例，写前同项目同类型未处置去重）；（c）落 `coverage_gap` 锚（见 1.2）。`origin_files` 为空/manifest 缺失损坏/判定异常时 MUST NOT 按比例降格。同一 run 只降格一次；幂等以同 run id 判定，异 run 陈旧锚不得抑制。
- [x] 1.2 core/agent_runner/maintenance_runs.py：缺口超阈值时调用 `core/code_review.py::write_pending_writeoff`，payload `{run_id, reason: "coverage_gap", attempts, at, gap}`。**仅非重派 run 新写锚**；重派 run 绝不改指锚（保持既有 :3416 链根不变量）。重派 run 仍超阈值时在原锚（run_id 不变）上递增 `attempts`；达 `CODE_REVIEW_COVERAGE_GAP_MAX_RESUME=2` 时 `clear_pending_writeoff` 清锚并升级告警「连续 N 轮续审未收敛」，停止自动续审（写入侧收口，消费侧零改动）。与 :3416 重启旗标锚同一收尾命中时至多写一次锚，旗标锚优先。缺口 ≤ 阈值保持现行为（WARNING 留痕、success 终态、不落新锚）。
- [x] 1.3 agents/code-review.md：补批次**计划声明**义务——派发任何批次前先把批次计划（批号 `b<N>` + 各批文件清单）原子写入 `.fenix/code-review/plan-<run_id>.json`（不派子代理时写单批/空计划），并扩写「唯一允许的写操作」边界纳入该文件（`core/code_review.py` 无批次派发逻辑，分批由 agent 自决，见 design 改动点 2）。core/agent_runner/maintenance_runs.py：`run_code_review` 收尾读计划与「分片+主产物」实际覆盖对账，计划中存在但零结果行的批记「计划缺批」，落 WARNING 并计入覆盖缺口告警正文；计划缺失/损坏留痕「无计划可对账」不阻塞收尾；该对账不改变既有终态判定。

## 2. 测试

- [x] 2.1 tests/test_code_review_coverage_gate.py：覆盖——非重派超阈值时 `success=False`+`coverage_partial`+run_metrics `terminal="partial"`+告警落盘+锚写入且同 run 幂等；低于/等于阈值时 success 保持且不落新锚、无信号；origin 空或 manifest 缺失时不降格；重派超阈值不改指锚、attempts 递增至上限后清锚升级告警；异 run 陈旧锚不抑制降格；批次计划缺批对账能暴露且不改变终态。
- [x] 2.2 回归既有 tests/test_code_review_salvage_writeoff.py 与 tests/test_code_review_night_resume.py，确认 error/restart 锚语义与夜间续跑行为不被破坏。

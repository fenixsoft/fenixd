## Deliverables

```yaml
- path: core/agent_runner/latency.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/self_review.py
  kind: modify
- path: tests/test_api_stall_signal_grading.py
  kind: new
- path: tests/test_run_latency_stats.py
  kind: modify
```

## 1. stall 信号分级

- [x] 1.1 core/agent_runner/latency.py：新增 STALL_ROUND_ESCALATE_SECONDS=300.0 常量与 classify_round_stall 分级纯函数（单轮 >300 秒返回 warning-escalated；连续 ≥2 轮 >120 秒返回 warning；其余 >120 秒单轮返回 info），不改动 LATENCY_STALL_SECONDS/STALL_ROUND_WARN_SECONDS/RUN_STALL_ROUND_SECONDS 三既有常量的取值与语义
- [x] 1.2 core/agent_runner/runner.py 发射点（:6184-6198）接入分级：info 级改以 INFO 落日志（事件名仍 api_round_stall、context 增 grade 字段），warning/warning-escalated 保留 WARNING；run 结束汇总行（format_latency_summary 渲染处）追加分级计数 warning=N info=M
- [x] 1.3 core/agent_runner/runner.py：成功终态调用 _log_run_metrics（:8687-8778）处传入本 run latency 统计，使终态日志行 latency_rounds/latency_stalls/latency_max 反映实际值而非 0/0/None（run 档案 jsonl 行构建处 :6819-6847 既有字段不动；数据通路：stats 为 _run_agent 局部量，经其返回 tuple 携带 → 成功调用点 :3804 → _finalize_success 新增参数 → latency= 传 _log_run_metrics，提前终态路径维持零样本回退）

## 2. 每日自省摘要可见性

- [x] 2.1 core/self_review.py：collect_daily_summary（:1651）第 6 节（:1754-1794）新增 API 停滞聚合行，逐个列出当日 stall 计数>0 的 run（run_id、stall 次数、累计停滞秒、最大单轮秒），数据复用 latency_samples_from_events/latency_stats；不改动 MIDFLIGHT_OUTLIER_DIMS（:774）与深扫行为（聚合环节随第 6 节既有降级契约：异常降级空产出 + warning；逐 run 扫描沿用 MIDFLIGHT_SCAN_MAX_LINES 有界流式口径，不整文件读入；累计停滞秒取 samples 中 >60s 样本之和）

## 3. 测试

- [x] 3.1 tests/test_api_stall_signal_grading.py（新建）：覆盖分级函数边界（恰 300 秒、恰连续第 2 轮、120-300 秒单轮）、发射点日志级别断言（info→INFO、escalated→WARNING）、成功终态 run metrics 日志行带非零 stall 统计
- [x] 3.2 tests/test_run_latency_stats.py：把既有「单轮 >120 秒必打 WARNING」断言更新为新分级语义；保留 60 秒统计口径与汇总行渲染的既有断言
- [x] 3.3 运行 pytest tests/test_api_stall_signal_grading.py tests/test_run_latency_stats.py tests/test_agent_runner_modules_contract.py 全绿（三常量同源契约不破）

## 验证修复（原地打回第 1 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/evo-api-stall-signal-grading/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码（复核结论：场景期望「聚合降级须留 warning」与 specs/api-stall-observability/spec.md 约束「聚合环节异常降级空产出 + warning」逐字一致，产品实际逐 run 静默吞异常零 warning——真实产品缺陷 BUG-01，修产品代码）
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码（core/self_review.py _collect_api_stall_aggregates：逐 run 扫描异常不再静默吞——部分失败逐 run _logger.warning 留痕并跳过，窗口内全部 run 扫描失败升级上抛交外层降级 handler 留 warning；补两条回归测试 test_sampling_failure_escalates_to_degradation_warning / test_partial_scan_failure_warns_and_keeps_rest）
- [x] 修复后重跑验证确认通过（tests/test_api_stall_signal_grading.py + tests/test_run_latency_stats.py + tests/test_agent_runner_modules_contract.py + tests/test_self_review_midflight.py + tests/test_daily_self_review.py + tests/test_run_stall_accounting.py 共 177 passed，含复现探测形态的降级 warning 断言全绿）

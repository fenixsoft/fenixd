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

- [ ] 1.1 core/agent_runner/latency.py：新增 STALL_ROUND_ESCALATE_SECONDS=300.0 常量与 classify_round_stall 分级纯函数（单轮 >300 秒返回 warning-escalated；连续 ≥2 轮 >120 秒返回 warning；其余 >120 秒单轮返回 info），不改动 LATENCY_STALL_SECONDS/STALL_ROUND_WARN_SECONDS/RUN_STALL_ROUND_SECONDS 三既有常量的取值与语义
- [ ] 1.2 core/agent_runner/runner.py 发射点（:6184-6198）接入分级：info 级改以 INFO 落日志（事件名仍 api_round_stall、context 增 grade 字段），warning/warning-escalated 保留 WARNING；run 结束汇总行（format_latency_summary 渲染处）追加分级计数 warning=N info=M
- [ ] 1.3 core/agent_runner/runner.py：成功终态调用 _log_run_metrics（:8687-8778）处传入本 run latency 统计，使终态日志行 latency_rounds/latency_stalls/latency_max 反映实际值而非 0/0/None（run 档案 jsonl 行构建处 :6819-6847 既有字段不动）

## 2. 每日自省摘要可见性

- [ ] 2.1 core/self_review.py：collect_daily_summary（:1651）第 6 节（:1754-1794）新增 API 停滞聚合行，逐个列出当日 stall 计数>0 的 run（run_id、stall 次数、累计停滞秒、最大单轮秒），数据复用 latency_samples_from_events/latency_stats；不改动 MIDFLIGHT_OUTLIER_DIMS（:774）与深扫行为

## 3. 测试

- [ ] 3.1 tests/test_api_stall_signal_grading.py（新建）：覆盖分级函数边界（恰 300 秒、恰连续第 2 轮、120-300 秒单轮）、发射点日志级别断言（info→INFO、escalated→WARNING）、成功终态 run metrics 日志行带非零 stall 统计
- [ ] 3.2 tests/test_run_latency_stats.py：把既有「单轮 >120 秒必打 WARNING」断言更新为新分级语义；保留 60 秒统计口径与汇总行渲染的既有断言
- [ ] 3.3 运行 pytest tests/test_api_stall_signal_grading.py tests/test_run_latency_stats.py tests/test_agent_runner_modules_contract.py 全绿（三常量同源契约不破）

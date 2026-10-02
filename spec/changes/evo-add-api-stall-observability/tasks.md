## Deliverables

```yaml
- path: core/agent_runner/latency.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_run_latency_stats.py
  kind: modify
- path: tests/test_run_stall_accounting.py
  kind: new
```

## 1. 落地实现

- [ ] 1.1 core/agent_runner/latency.py：新增模块级常量 `STALL_ROUND_WARN_SECONDS = 120.0`（run 期内单次 API 往返样本的 WARNING 阈值），附注释说明与既有 `LATENCY_STALL_SECONDS = 60.0`（统计口径）的语义分离、二者互不改写。
- [ ] 1.2 core/agent_runner/runner.py：在 `_run_claude` 在飞延迟采样点（tool_result→assistant 样本入列处，约 4995-5002 行旁路块）对样本 > `STALL_ROUND_WARN_SECONDS` 的情况经 `self.logger.warning("agent_runner", …)` 即时打一条日志，至少含 run_id、样本秒数（`:.1f` 格式）与轮序号（该样本在有效样本序列中的序数）；纯读侧，不改变流式处理时序、不 kill 进程、不重派、不触发人工告警，样本与 stats 结果与不加告警时逐字段一致。
- [ ] 1.3 core/agent_runner/runner.py：run 收尾两处指标落点补停滞字段——档案 run_metrics 行（`append_run_line` 的 `type: run_metrics`，约 5427-5440 行）与 daemon 侧 run metrics 结构化日志（`metric_type: run_metrics`，约 6807-6829 行）均新增 `latency_rounds`/`latency_stalls`/`latency_max` 三字段，取值直接复用 run 末延迟摘要已计算的同一 `latency_stats` 结果（约 5364-5377 行，禁止二次采样）；无样本时回退 `latency_rounds=0`、`latency_stalls=0`、`latency_max=None`，写入失败不阻断 run 收尾；既有字段与行序（run_metrics 行在终态行之后、恰一条）不变。

## 2. 测试

- [ ] 2.1 tests/test_run_latency_stats.py：扩展覆盖 1.1/1.2——`STALL_ROUND_WARN_SECONDS` 常量值；样本 >120s 时在飞采样点产出 WARNING（内容含 run_id 与样本秒数）、样本 ≤120s（含 119.9 边界）不产出；timestamp 缺失/负差值无效测量既不产样本也不触发 WARNING；触发 WARNING 前后 `latency_stats` 结果不变（纯读侧）。
- [ ] 2.2 tests/test_run_stall_accounting.py（新文件，参照 `tests/test_daemon_lifecycle_races.py::test_run_claude_poll_loop_crash_writes_error_terminal` 的 `_run_claude` 假 Popen 装配）：覆盖 1.3——带停滞样本的 run 收尾后档案 run_metrics 行含 `latency_rounds`/`latency_stalls`/`latency_max` 且与预期 stall 统计一致、仍恰一条 run_metrics 行且位于终态行之后；daemon 侧 run metrics 日志 context 含同名字段同值；零样本 run 字段回退 0/None 不抛；轮询环崩溃路径下 run_metrics 行照常追加、字段缺省不抛。
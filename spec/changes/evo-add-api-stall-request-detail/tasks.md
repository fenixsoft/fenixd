## Deliverables

```yaml
- path: core/agent_runner/latency.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_api_stall_request_detail.py
  kind: new
```

## 1. 停滞观测补全

- [ ] 1.1 core/agent_runner/runner.py：修复 api_round_stall 事件（_stall_ctx 构造点，约 :7784-7798）input_tokens/cache_read_input_tokens 恒 0 的填充缺陷，并新增字节级请求体积字段 request_bytes（流式场景取累计 chunk 字节，取不到置 null，事件不因体积缺失丢弃）
- [ ] 1.2 core/agent_runner/runner.py：run_metrics 终态落盘（约 :8583-8616）新增 stall_details 逐停滞明细数组（每项含停滞轮次号/相对 run 起点时刻偏移/时长秒/请求体积），既有聚合字段（latency_rounds/latency_stalls/latency_max/latency_stall_total_seconds）名称与语义不变
- [ ] 1.3 core/agent_runner/latency.py：format_latency_summary（:251，f-string :276）追加停滞合计秒数（复用既有 latency_stall_total_seconds 统计键）与停滞轮请求体积合计

## 2. 测试

- [ ] 2.1 tests/test_api_stall_request_detail.py：覆盖停滞事件 token 字段非恒 0 与 request_bytes 采集（含 null 回退）、run_metrics stall_details 数组结构、汇总行新字段渲染
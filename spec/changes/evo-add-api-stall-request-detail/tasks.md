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

- [x] 1.1 core/agent_runner/runner.py：api_round_stall 事件（_stall_ctx，runner.py:7962-7973）token 字段语义修正——先复核是否存在「assistant usage 非零而事件仍写 0」的样本（若有，属真正的填充缺陷需单独定位）；正常路径按判定落值：usage 非全零 → 真实 input_tokens/cache_read_input_tokens + `usage_source="assistant_usage"`；usage 缺失或逐消息全零（网关不回传）→ 字段置 **null** + `usage_source="unavailable"`。MUST NOT 静默写 0 冒充数据。
- [x] 1.2 core/agent_runner/runner.py：新增 request_bytes 采集——术语定义见 spec（截至该轮请求前本 attempt 已写入 run 转录的累计 JSON 行字节估算，prompt 体积代理）。在读线程逐行落盘处（runner.py:8005-8009）累加 `len(_line)`，样本完成时快照；**不取 stdout 响应字节**。取不到置 null，事件不因体积缺失丢弃。
- [x] 1.3 core/agent_runner/runner.py：逐停滞明细采集——样本完成点（runner.py:7902-7907）`_sb_sample > LATENCY_STALL_SECONDS`（60s）即追加 `{round, ts, duration_s, request_bytes, input_tokens, cache_read_input_tokens, usage_source}` 到 `latency_state["stall_details"]`，独立于 >120s 告警分支（覆盖 (60,120] 区间）。`offset_s` 在读线程 join 后的收尾块用 `ts - started_at` 计算；MUST NOT 在读线程直接引用 started_at（其于 runner.py:8077 读线程启动后才赋值）。
- [x] 1.4 core/agent_runner/runner.py：run_metrics 终态落盘（转录行 runner.py:8770-8813、日志侧 :8826 起）新增 `stall_details` 数组与 `latency_stall_bytes_total` 键；既有聚合字段（latency_rounds/latency_stalls/latency_max/latency_stall_total_seconds）名称与语义不变；`latency_stats` 既有签名与既有键不变（core/self_review.py:1746/:1915 调用点零改动），明细由 runner 侧附着到 stats。
- [x] 1.5 core/agent_runner/latency.py：format_latency_summary（:251，f-string :276）追加停滞合计秒数（复用 latency_stall_total_seconds）与停滞轮请求体积合计（latency_stall_bytes_total）；两键缺失时行形态与历史逐字节一致（bin/analyze_run_latency.py 零改动）。

## 2. 测试

- [x] 2.1 tests/test_api_stall_request_detail.py：覆盖 (a) usage 可得 run 的 token 非空与 usage_source="assistant_usage"；(b) usage 全零/缺失 run 的 token=null、usage_source="unavailable" 且 request_bytes 非空；(c) request_bytes 的 null 回退；(d) stall_details 数组结构、offset_s 口径，且覆盖 (60,120] 区间样本；(e) run_metrics 两落点与汇总行新字段渲染。仅「字段在场」不构成通过。
- [x] 2.2 tests/test_api_stall_request_detail.py：回归断言 latency_stats 既有键值不变、self_review.py:1746/:1915 两调用点行为不变、stall_details 为可选增键（缺键读侧不报错）。

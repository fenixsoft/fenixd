# 能力：api-stall-request-detail（API 停滞请求明细观测）

## 术语
- API 停滞（stall）：单次模型请求往返时长超过 60 秒（LATENCY_STALL_SECONDS）的等待轮，停滞轮零 token 产出。
- 逐停滞明细：run 终态 run_metrics 中按停滞轮次展开的数组记录。

## 行为规范
1. api_round_stall 事件必须携带：停滞轮次（latency_round，既有）、单次最大往返时长（latency_max，既有）、本轮真实 input_tokens 与 cache_read_input_tokens（修复恒 0 缺陷）、请求字节体积 request_bytes（新增；流式场景取累计 chunk 字节）。
2. run_metrics 终态必须新增 stall_details 数组：每项含停滞轮次号、相对 run 起点的时刻偏移、停滞时长秒、该轮请求字节体积；既有聚合字段（latency_rounds/latency_stalls/latency_max/latency_stall_total_seconds）保持字段名与语义不变。
3. 停滞汇总行（format_latency_summary）追加停滞合计秒数（复用既有 latency_stall_total_seconds 统计键，当前未入汇总行）与停滞轮请求体积合计。
4. 体积不可得时允许置 null；事件与明细不因体积缺失而丢弃。
# 能力：api-stall-request-detail（API 停滞请求明细观测）

## 术语
- API 停滞（stall）：单次模型请求往返时长超过 60 秒（LATENCY_STALL_SECONDS）的等待轮，停滞轮零 token 产出。
- 逐停滞明细：run 终态 run_metrics 中按停滞轮次展开的数组记录，**覆盖全部 >60s 停滞轮**（含 (60,120] 区间——该区间不产 api_round_stall 事件，但必须进明细），与 latency_stalls 计数同口径。
- 请求体积（request_bytes）：截至该轮请求发出前，本 attempt 已写入 run 转录的累计 JSON 行字节估算（prompt 体积代理；不取 stdout 响应字节，响应体积不能代表请求体积）。不可得时置 null。
- token 可用性（usage_source）：`assistant_usage` = 同轮 assistant 事件 `message.usage` 可得且非全零；`unavailable` = 网关逐消息不回传/字段缺失，逐轮 token 不可得（置 null，不写 0）。

## 行为规范

1. api_round_stall 事件必须携带：停滞轮次（latency_round，既有）、单次最大往返时长（latency_max，既有）、本轮 input_tokens 与 cache_read_input_tokens（可得时为真实值，否则 null）、usage_source、请求字节体积 request_bytes（新增，可为 null）。
2. run_metrics 终态必须新增 stall_details 数组：每项含停滞轮次号、相对本 attempt 起点的时刻偏移 offset_s、停滞时长秒、请求字节体积、该轮 token 与 usage_source；覆盖全部 >60s 停滞轮（含 ≤120s 不产事件的轮）。既有聚合字段（latency_rounds/latency_stalls/latency_max/latency_stall_total_seconds）保持字段名与语义不变。
3. 停滞汇总行（format_latency_summary）追加停滞合计秒数（复用既有 latency_stall_total_seconds 统计键）与停滞轮请求体积合计（新增统计键）；新键缺失时行形态与历史一致。
4. 体积不可得时允许置 null；事件与明细不因体积缺失而丢弃。token 不可得时 MUST 置 null 并标注 `usage_source="unavailable"`，MUST NOT 写 0 冒充真实用量。
5. 首采集验收：新字段必须在两类 run 上分别验证——usage 可得的 run 产出非空 token 且 usage_source="assistant_usage"；usage 全零/缺失的 run 产出 null + usage_source="unavailable" 且 request_bytes 非空；并验证 stall_details 覆盖 (60,120] 区间样本。仅「字段在场」不构成验收通过。
6. 以上均为纯读侧旁路：不改变流式事件处理时序、不新增事件类型、不阻断/不重杀 run、不新增配置键、不接入独立人工告警。

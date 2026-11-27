# 设计：api_round_stall 请求明细

## 现状锚点（2026-11-27 回源核实）
- 停滞汇总行：core/agent_runner/latency.py:251 format_latency_summary，f-string 在 :276 发出 stalls>60s=…；阈值 LATENCY_STALL_SECONDS=60.0（:23）；统计键 latency_stall_total_seconds 已存在（latency.py:234-236）但未进汇总行。
- 统计函数：latency_stats（latency.py:192）**只接收时长列表**，返回聚合键；core/self_review.py:1746/:1915 亦调用它（车道日汇总）。签名/既有键变更会波及该消费方。
- 停滞事件：core/agent_runner/runner.py:7931-7993 的 >120s 分支构造 _stall_ctx（:7962-7973）；其 input_tokens/cache_read_input_tokens 直接取同轮 assistant 事件已解析的 `_inp`/`_cr`（:7802-7817）。
- **恒 0 根因**：并非 _stall_ctx 填充遗漏——代码已从唯一可得来源（assistant `message.usage`）取数。部分网关逐消息不回传 usage（assistant usage 全零/缺失），真实用量仅在 run 末 result 终态（runner.py:8645-8661 终局回填注释；知识页 run-metrics-usage-backfill）。这类 run 的逐轮 token 在运行期不可得，任何「再取一次 request usage」都取不到。
- 延迟样本完成点：runner.py:7893-7907（`_sb_sample = e_ts - last_tool_result_ts`），样本仅存时长（`latency_state["samples"]`），**不保留时间戳与字节元数据**。
- 读线程与起点时钟：读线程 t_out/t_err 于 runner.py:8051-8055 启动，而 `started_at = time.time()` 在 :8077 才赋值——读线程内直接引用 started_at 存在 UnboundLocalError 窗口。
- run_metrics 落盘：转录行 runner.py:8770-8813，日志侧 :8826 起，现含 latency_rounds/latency_stalls/latency_max/latency_stall_total_seconds，无逐停滞明细。

## 方案
1. **token 语义修正（不承诺修复不可得网关）**：_stall_ctx 取同轮 `_inp`/`_cr`（现状），新增判定——两者至少一个非零 → 保留真实值 + `usage_source="assistant_usage"`；缺失或逐消息全零 → 字段置 **null** + `usage_source="unavailable"`。MUST NOT 用 0 冒充真实用量。
2. **request_bytes 定义与采集**：定义为「截至该轮请求发出前，本 attempt 已写入 run 转录的累计 JSON 行字节估算」——它是 prompt 体积的可得代理，与 usage 是否可得无关。取值点：读线程逐行落盘处（runner.py:8005-8009）累加 `len(_line)`；样本完成时快照当前累计值。**不取 stdout 响应字节**（响应体积不能代表请求体积）。累计器未初始化/异常时置 null，事件不因缺失丢弃。
3. **逐停滞明细采集点（独立于 120s 告警分支）**：在样本完成点（runner.py:7902-7907）判定 `_sb_sample > LATENCY_STALL_SECONDS`（60s）时，向 `latency_state["stall_details"]` 追加 `{round, ts, duration_s, request_bytes, input_tokens, cache_read_input_tokens, usage_source}`。`round` 取 `len(samples)`；`ts` 存绝对 epoch 秒（e_ts）。**offset_s MUST 在读线程 join 后的收尾块用 `ts - started_at` 计算**，MUST NOT 在读线程直接引用 started_at（见现状锚点）。这样 stall_details 覆盖全部 >60s 轮（含 (60,120] 不产事件的轮），与 latency_stalls 计数同口径。
4. **统计结构与序列化**：`latency_stats(samples)` 既有签名与既有键**不变**（self_review 两调用点零改动）。明细由 runner 侧把 `latency_state["stall_details"]` 附着到 stats 字典（或在 runner 收尾块单独组装），并新增统计键 `latency_stall_bytes_total`（明细 request_bytes 求和；无字节样本为 0.0）。run_metrics 转录行与日志侧行新增 `stall_details` 数组与 `latency_stall_bytes_total`；既有聚合键名/语义不变，读侧缺键按无明细/0 处理（向后兼容）。
5. **汇总行**：format_latency_summary 在既有 `stalls>60s=…` 后追加停滞合计秒数（复用 latency_stall_total_seconds）与停滞轮请求体积合计（latency_stall_bytes_total）；两键缺失时输出与历史逐字节一致（bin/analyze_run_latency.py 等无新键的调用方零改动）。
6. **纯读侧纪律**：全部为读侧旁路——不改流式事件处理时序、不新增事件类型、不阻断/不重杀 run、不新增配置键、不接入独立人工告警。

## 与存量边界
- evo-add-lane-stall-daily-budget-accounting（在途已实现）：车道日聚合口径不变；latency_stats 既有键不改，self_review.py:1746/:1915 行为不变。
- evo-add-api-stall-disposition-closeout（归档）：其补入字段由本 SPEC **修正语义**（可得则真实值、不可得则 null+来源标注），并新增逐停滞明细与字节体积。这是「字段在场但恒 0」的接续推进，而非再次声称填充缺陷。
- run-metrics-usage-backfill（知识页）：run 级终局回填（result.usage）语义不变；本 SPEC 的逐轮 token 仅在其可获得时填写，不与之混用，`usage_source` 取值（assistant_usage/unavailable）与该页的 final_result_backfill 标注不冲突（后者仅落 run_metrics 行）。

## 首采集验收（可观测性交付，与功能同批）
测试/验收 MUST 同时覆盖两类 run，且**仅「字段在场」不构成通过**：
- usage 可得的 run：事件与 stall_details 的 token 非空、`usage_source="assistant_usage"`；
- usage 全零/缺失的 run：token 为 null、`usage_source="unavailable"`，而 `request_bytes` 仍非空；
- stall_details 覆盖 (60,120] 区间样本（证明采集点独立于 120s 告警分支）；
- 汇总行与 run_metrics 两落点渲染正确。
此条直接针对上一个 SPEC「字段落地后实测恒 0、验收仍 pass」的失效模式。

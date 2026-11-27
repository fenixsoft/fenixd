# 提案：api_round_stall 事件补请求体积与逐停滞明细

## 背景与动机
周期评审/修复链已连续 9 个评审日出现 API 停滞（单次往返超 60 秒的空等），2026-11-22 窗口两 run 合计空等 792.5 秒（326.9+465.6，分别占两 run 墙钟 82.7%/56.1%），拉长交付约 13 分钟。停滞归因假说（上游负载排队/prefill 放大/网络链路）因观测字段缺失无法裁决：api_round_stall 事件虽在 evo-add-api-stall-disposition-closeout 补入 input_tokens/cache_read_input_tokens，但实测恒 0（2026-11-22 窗 6 条事件 tokens 全 0）形同虚设；run_metrics 终态只有停滞聚合（latency_rounds/latency_stalls/latency_max/latency_stall_total_seconds），无逐停滞轮次明细。本立项已挂账 4 天（2026-11-19 登记）。

> **恒 0 的根因不是单一「填充缺陷」**：`_stall_ctx` 已经从同轮 assistant 事件的 `message.usage` 取数（runner.py:7802-7817 → :7962-7973）；而「网关逐消息不回传 usage、真实用量仅在 result 终态」的 run（runner.py:8645-8661；知识页 spec/knowledge/domains/agent-runtime/run-metrics-usage-backfill.md），在此路径上逐轮用量本就不可得。故本 SPEC 不承诺「把恒 0 一定修成非 0」，而是把语义修正确：usage 可得时填真实值，不可得时置 null 并标注来源，同时补一条**不依赖 usage** 的字节级请求体积证据。

## 目标
1. 停滞事件 token 字段语义修正：usage 可得（同轮 assistant `message.usage` 非全零）时填本轮真实 input_tokens/cache_read_input_tokens；不可得时置 **null** 并落 `usage_source="unavailable"`，使「无数据」与「真实值为 0」可区分，不再静默写 0 冒充数据。
2. 补字节级请求体积与停滞轮次上下文：api_round_stall 事件与 run_metrics 逐停滞明细均携带该轮请求体积（定义见 design 与 spec 术语；取不到置 null）。
3. run_metrics 终态新增逐停滞明细数组 stall_details（轮次/相对起点的时刻偏移/时长/请求体积/token 与可用性），覆盖全部 >60s 停滞轮；积累足够样本（预计 ≥2 个评审日，以实际样本量为准）即可裁决或排除 prefill 放大假说。

## 非目标
- 不改变停滞判定阈值（60 秒）与车道日停滞预算记账（evo-add-lane-stall-daily-budget-accounting 已实现，车道日 1800 秒观察维持）。
- 不做任何自动降载/重试策略变更——本 SPEC 只补观测，修复方向待证据积累后另行立项。
- 不改变网关/CLI 的 usage 上报行为，不为不可得的逐轮 token 伪造数值。

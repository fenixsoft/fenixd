# 提案：api_round_stall 事件补请求体积与逐停滞明细

## 背景与动机
周期评审/修复链已连续 9 个评审日出现 API 停滞（单次往返超 60 秒的空等），2026-11-22 窗口两 run 合计空等 792.5 秒（326.9+465.6，分别占两 run 墙钟 82.7%/56.1%），拉长交付约 13 分钟。停滞归因假说（上游负载排队/prefill 放大/网络链路）因观测字段缺失无法裁决：api_round_stall 事件虽在 evo-add-api-stall-disposition-closeout 补入 input_tokens/cache_read_input_tokens，但实测恒 0（2026-11-22 窗 6 条事件 tokens 全 0）形同虚设；run_metrics 终态只有停滞聚合（latency_stalls/latency_max/latency_stall_total_seconds），无逐停滞轮次明细。本立项已挂账 4 天（2026-11-19 登记）。

## 目标
1. 修复停滞事件 token 字段恒 0 的填充缺陷，补字节级请求体积与停滞轮次上下文。
2. run_metrics 终态新增逐停滞明细数组（轮次/时刻偏移/时长/请求体积），积累两个评审日即可裁决或排除 prefill 放大假说。

## 非目标
- 不改变停滞判定阈值（60 秒）与车道日停滞预算记账（evo-add-lane-stall-daily-budget-accounting 已实现，车道日 1800 秒观察维持）。
- 不做任何自动降载/重试策略变更——本 SPEC 只补观测，修复方向待证据积累后另行立项。
# 设计：api_round_stall 请求明细

## 现状锚点（2026-11-23 回源核实）
- 停滞汇总行：core/agent_runner/latency.py:251 format_latency_summary，f-string 在 :276 发出 stalls>60s=…；阈值 LATENCY_STALL_SECONDS=60.0（:23）；统计键 latency_stall_total_seconds 已存在（:234-236）但未进汇总行。
- 停滞事件：core/agent_runner/runner.py:7784-7798（_stall_ctx 构造 api_round_stall），现有字段 run_id/event/latency_round/latency_max/grade/input_tokens/cache_read_input_tokens/provider；token 字段恒 0 是填充缺陷（归档 SPEC evo-add-api-stall-disposition-closeout 落地后从未产数）。
- run_metrics 落盘：core/agent_runner/runner.py:8583-8616（日志侧 :8645 起），现含 latency_stalls/latency_max/latency_stall_total_seconds，无逐停滞明细。

## 方案
1. 恒 0 缺陷修复收敛在 _stall_ctx：从本轮请求 usage/请求对象直接取 token 数；request_bytes 流式场景用累计 chunk 字节，取不到置 null。
2. 明细数组挂在既有停滞统计结构上（轮次/偏移/时长/体积），run_metrics 序列化时随终态落盘；汇总行追加合计秒与体积合计。
3. 兼容：新字段全部可选（null 安全），消费方（admin_monitor 车道日停滞记账、每日摘要）零改动即可运行。

## 与存量边界
- evo-add-lane-stall-daily-budget-accounting（在途已实现）：车道日聚合口径不变。
- evo-add-api-stall-disposition-closeout（归档）：其补入字段由本 SPEC 修复填充缺陷——属「上次修复落地后问题仍复发（字段在场恒 0）」的推翻式推进，差异即本次新增逐停滞明细与字节级体积。
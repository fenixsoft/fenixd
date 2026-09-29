# Run 级 API 延迟直方图
<!-- knowledge: capability=run-latency-observability rev=2
     sources=spec/archive/2026-09-11-add-planner-efficiency,spec/archive/2026-09-18-fix-run-latency-toolresult-parser -->

在 run 结束时输出 API 往返延迟画像（中位/p90/长尾占比），区分「卡死」与「慢而不死」，替代事后转录考古。

## 规则

- **在线延迟统计（纯读侧）**：`_run_claude` 流式循环从事件 timestamp（`_parse_event_timestamp`）统计 API 往返等待。样本配对口径：以「tool_result 事件 → 下一个 assistant 事件」的时间间隔归类为一次 API 往返样本；tool_result 按 `tool-result-stream-detection` 统一识别（`user` 事件包裹 `tool_result` content block，或兼容的顶层 `tool_result` 事件）；识别出的事件须携带 timestamp 才参与配对（缺失则跳过）；非 tool_result 的 `user` 事件（纯 text block，如 skill 加载消息）不产生样本。统计不得改变流式处理行为与时序。
- **run 末摘要日志**：run 结束（成功或失败）打一行摘要，至少含轮数、中位、p90、max、>60s 长尾计数及占比（如 `run planner-plan-xxx-a1: 58 rounds, median 3.2s, p90 78s, max 185s, stalls>60s=15 (26%)`），可按 run_id 检索。真实 stream-json 转录须产出非空样本（rounds>0，p90/median/max 为真实样本的非 null 值）；无样本时的摘要文案不得将「识别不到 tool_result」表述为「旧转录跳过」等归因于输入文件的误导性措辞。
- **失败 run 附延迟证据**：run 失败（超时/异常/turn 上限）时，错误上下文附延迟摘要（轮数与长尾占比），区分「卡死（零进展+超时）」与「慢而不死（长尾密集）」，供 admin/人工判定网关慢而非进程死锁。
- **事后分析脚本**：`bin/analyze_run_latency.py <run.jsonl...>` 对任意历史转录输出与在线摘要同口径的直方图，支持批量扫描与按延迟排序；损坏/空文件容错（跳过并报告）。
- **延迟观测自检**：run 末若 `latency_rounds == 0` 而 assistant 事件计数 `turn_count > 0`（有模型轮次却配不出任何样本，为解析器失明的确定信号），输出显式 WARNING 日志（含 run_id 与 `latency_rounds=0` / `turn_count` 数值）。真空跑（rounds=0 且 turn_count=0，如启动即失败）不触发。
- **告警纪律**：延迟数据与失明自检 MUST NOT 触发独立人工告警/admin 唤醒（可观测数据≠告警源）；暴露面限于 run 末摘要日志与失败证据附加。dashboard 直方图展示为可选增强，不属验收范围。

## 溯源

- [2026-09-11 2026-09-11-add-planner-efficiency](spec/archive/2026-09-11-add-planner-efficiency/) — 新增在线延迟统计与 run 末摘要日志、失败 run 延迟证据附加、`bin/analyze_run_latency.py` 事后分析脚本，并确立不产生独立人工告警的纪律。
- [2026-09-18 2026-09-18-fix-run-latency-toolresult-parser](spec/archive/2026-09-18-fix-run-latency-toolresult-parser/) — tool_result 识别改按 `tool-result-stream-detection` 统一口径（user 事件包裹 block 曾致样本全盲），新增非 tool_result user 事件排除、真实转录非空样本验收与「有轮次零样本」失明自检 WARNING。

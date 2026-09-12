# run-latency-observability — 增量规格（tool_result 识别修复 + 观测自检）

## MODIFIED Requirements

### Requirement: 在线延迟统计与 run 末摘要日志

`_run_claude` 流式循环 SHALL 从事件 timestamp（已在盘，`_parse_event_timestamp`）读侧统计 API 往返等待：以「tool_result 事件（按 `tool-result-stream-detection` 统一识别，即 `user` 事件包裹 `tool_result` content block，或兼容的顶层 `tool_result` 事件）→ 下一个 assistant 事件」的时间间隔归类为一次 API 往返样本，识别出的事件 MUST 携带 timestamp 才参与配对（缺失则跳过）。run 结束（成功或失败）SHALL 打一行摘要日志，至少含：轮数、中位、p90、max、>60s 长尾计数及占比（如 `run planner-plan-xxx-a1: 58 rounds, median 3.2s, p90 78s, max 185s, stalls>60s=15 (26%)`）。统计为纯读侧，MUST NOT 改变流式处理行为与时序。无样本时的摘要日志文案 MUST NOT 将「识别不到 tool_result」表述为「旧转录跳过」等归因于输入文件的误导性措辞。

#### Scenario: 摘要日志可检索

- **WHEN** 任意 agent run 结束
- **THEN** 日志出现该 run 的延迟摘要行（含 run_id），可按 run_id 检索

#### Scenario: 统计不改变行为

- **WHEN** 流式事件到达（无论间隔长短）
- **THEN** 事件处理时序与统计前一致（纯旁路记录，无阻塞/无重试逻辑变更）

#### Scenario: 真实 stream-json 转录产出非空样本

- **WHEN** run 转录为真实 stream-json 形态（工具结果以 `user` 事件包裹 `tool_result` block 承载，事件带 ISO timestamp，无任何顶层 `tool_result` 事件）
- **THEN** run 末延迟摘要 `rounds` > 0，且 `p90` / `median` / `max` 为基于真实样本的非 null 值（不再全盲）

#### Scenario: 非 tool_result 的 user 事件不产生样本

- **WHEN** 转录中的 `user` 事件为纯 `text` block（如 skill 加载消息），前后为 assistant 事件
- **THEN** 该 `user` 事件 MUST NOT 作为待配对 tool_result，不产生 API 往返样本

### Requirement: 延迟观测自检

run 末计算延迟摘要时，若 `latency_rounds == 0` 而该 run 的 assistant 事件计数 `turn_count > 0`（即有模型轮次却配对不出任何样本，为解析器失明的确定信号），系统 SHALL 输出一条显式 WARNING 日志（含 run_id 与 `latency_rounds=0` / `turn_count` 数值），使观测盲区不再静默。该自检 MUST 仅为日志 WARNING，MUST NOT 触发独立人工告警/admin 唤醒（遵循本能力既有「延迟数据不触发独立人工告警」铁律）。

#### Scenario: 有轮次却零样本触发失明告警

- **WHEN** 一个 run 产生了 N > 0 个 assistant 事件，但延迟采样结果为 0 轮样本
- **THEN** 输出 WARNING 日志，明示「延迟观测疑似失明（rounds=0 但 assistant 轮次=N）」，含 run_id

#### Scenario: 真空跑不误报

- **WHEN** 一个 run 未产生任何 assistant 事件（rounds=0 且 turn_count=0，如启动即失败）
- **THEN** MUST NOT 输出失明告警（0 样本为合理结果）

#### Scenario: 自检不产生 admin 告警

- **WHEN** 失明告警被触发
- **THEN** 仅产生日志行，不写入 admin_alerts、不唤起 Administrator agent

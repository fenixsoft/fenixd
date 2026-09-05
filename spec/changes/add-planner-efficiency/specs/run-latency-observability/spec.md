# run-latency-observability — run 级 API 延迟直方图

## ADDED Requirements

### Requirement: 在线延迟统计与 run 末摘要日志

`_run_claude` 流式循环 SHALL 从事件 timestamp（已在盘，`_parse_event_timestamp`）读侧统计 API 往返等待：相邻事件间隔中「tool_result → 下一个 assistant 事件」归类为 API 往返样本。run 结束（成功或失败）SHALL 打一行摘要日志，至少含：轮数、中位、p90、max、>60s 长尾计数及占比（如 `run planner-plan-xxx-a1: 58 rounds, median 3.2s, p90 78s, max 185s, stalls>60s=15 (26%)`）。统计为纯读侧，MUST NOT 改变流式处理行为与时序。

#### Scenario: 摘要日志可检索

- **WHEN** 任意 agent run 结束
- **THEN** 日志出现该 run 的延迟摘要行（含 run_id），可按 run_id 检索

#### Scenario: 统计不改变行为

- **WHEN** 流式事件到达（无论间隔长短）
- **THEN** 事件处理时序与统计前一致（纯旁路记录，无阻塞/无重试逻辑变更）

### Requirement: 失败 run 附延迟证据

run 失败（超时/异常/turn 上限）时，错误上下文 SHALL 附延迟摘要——区分「卡死（零进展+超时）」与「慢而不死（长尾密集）」供 admin/人工诊断，替代事后转录考古。

#### Scenario: 超时 run 的证据含延迟画像

- **WHEN** agent run 超时被终止
- **THEN** 错误信息/处置上下文包含该 run 的延迟摘要（轮数与长尾占比），admin 可据此判定网关慢而非进程死锁

### Requirement: 事后分析脚本

提供 `bin/analyze_run_latency.py <run.jsonl...>`：对任意历史 run 转录输出同款直方图摘要（与在线摘要口径一致），支持批量扫描与按延迟排序。脚本 SHALL 对损坏/空文件容错（跳过并报告）。

#### Scenario: 历史转录可追溯

- **WHEN** 对既有 run 转录执行 `python3 bin/analyze_run_latency.py .fenix/runs/planner-plan-*.jsonl`
- **THEN** 逐文件输出与在线摘要同口径的延迟画像，损坏文件被跳过并报告

### Requirement: 不产生独立人工告警

延迟数据 MUST NOT 触发独立人工告警/admin 唤醒（告警降噪铁律：可观测数据≠告警源）；其暴露面限于 run 末摘要日志与失败证据附加。dashboard 侧展示（run 详情页直方图）为后续可选增强，不属本能力验收范围。

#### Scenario: 慢 run 不唤起 admin

- **WHEN**某 run 延迟 p90 超阈值但 run最终成功
- **THEN** 仅有摘要日志，无 admin_alerts 信号、无 Administrator 唤起

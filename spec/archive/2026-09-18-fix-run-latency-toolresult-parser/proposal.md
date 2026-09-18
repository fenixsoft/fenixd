# Proposal: fix-run-latency-toolresult-parser

## Why

窗口内全部 30 个 run 完成时延迟观测全盲（`latency_rounds=0` / `latency_stalls=0` / `latency_p90=null`），依赖该口径的秒挂/停滞检测与 `add-turn-limit-anchor-c` 锚点 C 的 unobserved 续期判定全部基于空数据运行。

根因经实证定位：解析器（及其测试、其归档 SPEC）基于一个**错误的事件形态假设**——假定 stream-json 转录存在顶层 `type: "tool_result"` 事件，而实际格式中工具结果一律以 `type: "user"` 事件承载，包裹在 `message.content[].type == "tool_result"` 的 content block 内。扫窗口内 12 条最新转录：顶层 `tool_result` 事件出现次数 **0/12**，工具结果 100% 走 `user` 事件（含 181/288 条带 ISO timestamp 的 assistant 行）。三处消费点共用这一错误判定，故全链失明；测试用**与生产代码共享同一错误前提的合成 schema** 自证，永远绿，缺陷从未暴露。

## What Changes

- **统一 tool_result 识别契约**：新增共享判定（`user` 事件包裹 `tool_result` block 为真；兼容存量顶层 `tool_result` 事件；`user` 文本事件——如 skill 加载消息——不得误判）作为三处消费点的单一真源。
- **三处消费点修复**：`latency_samples_from_events`（纯函数，含离线分析脚本 `bin/analyze_run_latency.py`）、`_run_claude` 内联读侧采样、`_turn_traffic_active`（turn-limit 续期活性证据 b）全部改用统一识别——延迟摘要与流量活性从「恒空 / 恒 False」恢复为真实观测。
- **观测自检**：run 末若 `latency_rounds == 0` 但 `turn_count > 0`（有 assistant 事件却配对不出样本 = 解析器失明的确定信号），输出显式 WARNING 日志（**不**触发独立人工告警，尊重既有告警降噪铁律）；并修正空样本文案——不再把真实失明报成「旧转录跳过」。
- **真实夹具测试**：新增以真实 stream-json 转录形态（`user` 包裹 `tool_result`）为输入的用例，断言样本数 > 0；根治「合成 schema 自我证明」的测试盲区。

## Capabilities

### New Capabilities

- `tool-result-stream-detection`: 流转录中 tool_result 事件的正确识别契约（`user` 包裹 block / 顶层兼容 / 非 tool_result `user` 排除），作为延迟采样与流量活性三处消费点的单一真源。

### Modified Capabilities

- `run-latency-observability`: 修改「在线延迟统计与 run 末摘要日志」——样本口径中的「tool_result 事件」改按统一识别契约判定（原前提错误致全盲）；并新增观测自检与空样本文案修正。
- `turn-limit-lifecycle`: 修改「轮次上限活性感知续期」——活性证据 b（尾部窗口 tool_result 流量）改按统一识别契约判定（原判定恒 False，护栏证据失效）。

## Impact

- `core/agent_runner/runner.py`：
  - 新增共享判定 helper（拟 `_entry_is_tool_result`，模块级 + 类静态双入口，复用既有 timestamp 解析先例）；
  - `latency_samples_from_events`（现 runner.py:449）改用 helper；
  - `_run_claude` 内联读侧采样（现 runner.py:3041-3052）改用 helper；
  - `_turn_traffic_active`（现 runner.py:1845-1891）改用 helper；
  - `format_latency_summary`（现 runner.py:516）空样本文案修正；
  - `_run_claude` finally 延迟摘要块（现 runner.py:3204）加自检告警。
- `bin/analyze_run_latency.py`：复用 `latency_samples_from_events`，helper 修复后自动获益（脚本本身无需改代码，但测试须覆盖真实形态）。
- `tests/test_run_latency_stats.py` / `tests/test_turn_limit_lifecycle.py`：现有合成 `_evt("tool_result", ...)` 用例保留（覆盖兼容路径），新增真实 stream-json 形态夹具用例。
- 不改：`_parse_event_timestamp`（timestamp 解析本已正确，问题在事件类型判定，不在字段提取）；`latency_stats` 分位/长尾计算口径；摘要行格式；告警降噪契约（自检仅日志，非 admin 告警）。
- 关联证据：`fenixd.log` 3373 行起「0 rounds（无 timestamp 样本，旧转录跳过）」30 连发；`.fenix/runs/impl-add-turn-limit-anchor-c-1789107200-a1.jsonl`（顶层 tool_result=0，`user` 包裹 tool_result=92，assistant 带 timestamp=181）。

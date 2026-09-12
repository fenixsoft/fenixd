# tool-result-stream-detection — 流转录 tool_result 事件识别契约

## ADDED Requirements

### Requirement: 流转录 tool_result 事件统一识别

系统 SHALL 以单一判定识别 stream-json 流转录中的 tool_result 事件：`type == "user"` 且其 `message.content` 为列表并含至少一个 `{"type": "tool_result", ...}` content block 的事件 SHALL 识别为 tool_result 事件；`type == "tool_result"` 的顶层事件 SHALL 同样识别（兼容存量合成/旧形态转录）；`message.content` 为字符串或仅含 `text` block 的 `user` 事件（如 skill 加载文本消息）MUST NOT 识别为 tool_result 事件。该判定 SHALL 为延迟采样（`latency_samples_from_events`、`_run_claude` 内联读侧采样）与流量活性（`_turn_traffic_active`）三处消费点的单一真源，三处 MUST 调用同一判定而非各自硬编码事件类型比较。

#### Scenario: user 事件包裹 tool_result block 识别为真

- **WHEN** 输入事件为 `{"type": "user", "timestamp": "...", "message": {"content": [{"type": "tool_result", "tool_use_id": "...", "content": "..."}]}}`
- **THEN** 统一判定返回真（该事件计为一个 tool_result 事件）

#### Scenario: 非 tool_result 的 user 文本事件识别为假

- **WHEN** 输入事件为 `{"type": "user", "timestamp": "...", "message": {"content": [{"type": "text", "text": "Base directory for this skill: ..."}]}}`（skill 加载消息形态）
- **THEN** 统一判定返回假，且 `latency_samples_from_events` 对该事件不产生样本、`_turn_traffic_active` 不因该事件判活性

#### Scenario: 顶层 tool_result 事件兼容识别为真

- **WHEN** 输入事件为 `{"type": "tool_result", "timestamp": 100.0}`（存量合成/旧形态）
- **THEN** 统一判定返回真（兼容路径，既有合成测试基线不受影响）

#### Scenario: user 事件含多个 tool_result block 仍计一个事件

- **WHEN** 输入 `user` 事件的 `message.content` 含两个及以上 `tool_result` block（并行工具调用回喂）
- **THEN** 统一判定返回真，且延迟采样对该事件只产生待配对的一个 tool_result 时间戳（一次 API 往返粒度）

#### Scenario: 非 user/tool_result 事件一律识别为假

- **WHEN** 输入事件 `type` 为 `assistant` / `system` / `result` / `tool_progress` / `stderr` / `provider_marker` 等
- **THEN** 统一判定返回假

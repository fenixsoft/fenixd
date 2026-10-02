<!-- knowledge: capability=tool-result-stream-detection rev=1 sources=spec/archive/2026-09-18-fix-run-latency-toolresult-parser -->

# 工具结果流事件识别

stream-json 流转录中 tool_result 事件的统一判定：三处消费点共用的单一真源。

## 现行规则

- 统一判定：`type == "user"` 且 `message.content` 为列表并含至少一个 `{"type": "tool_result", ...}` content block 的事件，识别为 tool_result 事件；`type == "tool_result"` 的顶层事件同样识别（兼容存量合成/旧形态转录）。
- 排除项：`message.content` 为字符串或仅含 `text` block 的 `user` 事件（如 skill 加载文本消息）不识别为 tool_result 事件；其余类型事件（`assistant` / `system` / `result` / `tool_progress` / `stderr` / `provider_marker` 等）一律识别为假。
- 单一真源：该判定为三处消费点的唯一实现——延迟采样（`latency_samples_from_events`、`_run_claude` 内联读侧采样）与流量活性（`_turn_traffic_active`）均调用同一判定，不各自硬编码事件类型比较。
- 计数粒度：`user` 事件含两个及以上 `tool_result` block（并行工具调用回喂）时仍计为一个事件；延迟采样对该事件只产生一个待配对的 tool_result 时间戳（一次 API 往返粒度）。识别为假的事件不产生延迟样本、不作为流量活性证据。

## 溯源

- 2026-09-18 fix-run-latency-toolresult-parser（spec/archive/2026-09-18-fix-run-latency-toolresult-parser） — 固化 tool_result 事件统一识别判定（user 包裹 block + 顶层兼容路径）、排除文本类 user 事件，并收敛为延迟采样与流量活性三处消费点的单一真源

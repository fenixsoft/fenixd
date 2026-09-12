# Design: fix-run-latency-toolresult-parser

## Context

`run-latency-observability`（09-11 归档）与 `turn-limit-lifecycle`（add-turn-limit-anchor-c 在途）两条能力都消费「run 流转录里的 tool_result 事件」，但二者的实现均硬编码 `entry["type"] == "tool_result"`。实证（窗口内 12 条最新转录）证明：`claude -p --output-format stream-json` **从不产生顶层 `tool_result` 事件**，工具结果一律以 `type == "user"` 事件承载，包裹在 `message.content[]` 中 `{"type": "tool_result", ...}` 的 content block 内（顶层 `tool_result` 计数 0/12，`user` 包裹 `tool_result` 每文件 7–155 个）。

后果分三层：
1. `_run_claude` 内联采样 `last_tool_result_ts` 恒 None → `samples` 恒空 → 延迟摘要 30 连发「0 rounds」。
2. `_turn_traffic_active`（turn-limit 续期活性证据 b）恒 False → 续期矩阵的「流量活性」分支死掉，只剩分支提交活性（证据 a）单腿支撑。
3. `latency_samples_from_events`（纯函数，离线分析脚本复用）同盲。

测试为何未拦住：`tests/test_run_latency_stats.py` 用 `_evt("tool_result", ts)` 构造**合成事件**，与生产代码共享同一错误前提（假定顶层 `tool_result` 事件存在），测试在自证，真实转录从不进入该路径。归档 SPEC 第 7 行也把「tool_result 事件」写成了事件类型，错误前提被规格固化。

## Goals / Non-Goals

**Goals:**

- 三处消费点统一改用**正确识别**，延迟摘要与流量活性从「恒空/恒 False」恢复为真实观测。
- 建立单一识别真源，防止三个消费点再次各自发散出错误的类型假设。
- 加观测自检：解析器失明（有 assistant 事件却 0 样本）时显式告警，不再静默。
- 加真实形态夹具测试，根治「合成 schema 自我证明」。

**Non-Goals:**

- 不改 `_parse_event_timestamp`：timestamp 字段提取本已正确（`assistant`/`user` 事件都带顶层 `timestamp`），问题在**事件类型判定**而非字段解析。
- 不改 `latency_stats` 分位/长尾计算、摘要行格式、离线脚本 CLI 形态。
- 不引入 admin 告警：自检是日志 WARNING，尊重 `run-latency-observability` 既有「延迟数据不触发独立人工告警」铁律。
- 不回溯修复历史转录的统计（只修解析器，历史文件下次分析时自然可读）。
- 不触碰 turn-limit 续期矩阵的窗口/步长/封顶常量（只修证据 b 的检测，不改矩阵结构）。

## Decisions

### D1: 单一共享识别 helper，而非三处各自修

新增模块级判定 `_entry_is_tool_result(entry) -> bool`（类内提供 `AgentRunner._entry_is_tool_result` 静态入口，沿用 `_parse_event_timestamp` 惰性引用先例），三处消费点全部调用它。

- **理由**：根因正是「三处独立硬编码同一错误假设」。若三处各自改，下次格式再变仍会发散；单一真源把「如何识别」收敛到一个可测点。
- **备选**：三处分别内联修正 → 否决（复现发散风险）。

### D2: 识别语义 = `user` 包裹 `tool_result` block ∪ 顶层 `tool_result`（兼容）

```
_is_tool_result(entry):
  if entry.get("type") == "tool_result":        # 存量兼容：合成/旧形态
      return True
  if entry.get("type") == "user":
      content = entry.get("message", {}).get("content")
      return isinstance(content, list) and any(
          isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
  return False
```

- **理由**：真实格式走 `user` 分支；顶层分支保留兼容现存合成测试与任何旧形态转录，避免本修复推翻既有测试基线。`user` 的 `message.content` 若为字符串或仅含 `text` block（如 skill 加载消息，实测 `impl-add-verify-preflight-gate` 第 9 行即此形态）→ 判 False，杜绝假样本。
- **备选**：只认 `user` 分支 → 否决（会打破现有合成用例且丢失旧格式兼容）。

### D3: 配对口径不变，仅识别入口变

保持「识别出的 tool_result 事件 ts → 下一个 `assistant` 事件 ts，差为一次 API 往返样本；配对一次后清空待配对」的既有语义。tool_result 事件的 timestamp 取承载它的事件（`user` 事件）的顶层 `timestamp`——该字段实测存在（92/92）。

- **并行工具调用**：一个 `user` 事件承载 N 个 `tool_result` block 仍算**一次** tool_result 事件（一次 API 往返），与「N 个并行工具结果回喂 → 下一个 assistant」的真实往返粒度一致。

### D4: 自检条件 = `latency_rounds == 0` 且 `turn_count > 0`

run 末（`finally` 延迟摘要块内），已算出 `stats["rounds"]` 且 `turn_count[0]` 在盘。二者组合能**确定**区分「真空跑」（0 assistant 事件，rounds=0 合理）与「解析器失明」（有 assistant 事件却配不出样本）。命中时输出 WARNING 日志（component=agent_runner + run_id），**不**写 admin_alerts。

- **理由**：这是把静默盲区变成可观测信号的最小增量，且不违反告警降噪（仅日志）。
- **备选**：对 `rounds==0` 无条件告警 → 否决（真空跑会误报噪音）。

### D5: 空样本文案修正 + 真实夹具测试

- `format_latency_summary` 的 0 样本分支文案「无 timestamp 样本，旧转录跳过」是**反向误导**（把解析器失明伪装成预期旧转录）。改为中性可诊断文案，区分「无样本（该 run 无 API 往返）」与失明自检信号。
- 测试新增：以真实 stream-json 形态（`user` 事件包裹 `tool_result` block + 带 ISO timestamp）构造夹具，断言 `latency_samples_from_events` 样本数 > 0、`_turn_traffic_active` 对窗口内真实形态判 True；并保留一条纯 `text` `user` 事件断言不产生样本/活性。

## Risks / Trade-offs

- [伪造样本风险] `user` 事件误判为 tool_result → 假延迟样本 / 假流量活性（该续不续、该杀不杀） → 缓解：D2 严格判定（必须含 `tool_result` block），并加「纯 text `user` 事件不识别」的负向测试。
- [续期行为变化] 证据 b 从恒 False 变真实 → turn-limit 续期可能比过去更频繁触发 extend → 缓解：证据 a（分支提交）未变，矩阵封顶（`TURN_EXTENSION_MAX`）与窗口常量不变，仅「有真实工具流量的 run」获得本应有的续期，符合 `turn-limit-lifecycle` 既定意图；design 固化「窗口/步长/封顶不变」。
- [兼容层长期腐化] 顶层 `tool_result` 兼容分支永远不命中真实数据 → 缓解：注释标注「兼容合成/旧形态」，不视为死代码（测试依赖）。
- [自检噪音] `rounds==0 且 turn_count>0` 若因其他原因（如全为无 timestamp 事件）命中 → 缓解：真实转录 assistant 100% 带 timestamp，误报面极窄；即便误报也只是 INFO/WARNING 日志，无副作用。

## Migration Plan

无数据迁移、无配置新增。纯代码修复：helper 落地 → 三处切换 → 文案/自检 → 测试。回滚 = revert 提交，无状态残留。

## Open Questions

- 无（识别语义、自检条件、兼容层均已定，实现无歧义）。

# Tasks: fix-run-latency-toolresult-parser

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_run_latency_stats.py
  kind: modify
- path: tests/test_turn_limit_lifecycle.py
  kind: modify
```

## 1. tool_result 统一识别 helper

- [ ] 1.1 在 `core/agent_runner/runner.py` 模块级新增 `_entry_is_tool_result(entry: dict) -> bool`：`type == "tool_result"` 返回真（兼容存量）；`type == "user"` 且 `message.content` 为列表且含至少一个 `{"type": "tool_result"}` block 返回真；其余（含 `message.content` 为字符串或仅 `text` block 的 `user` 事件）返回假。附 docstring 标注真实 stream-json 形态与兼容层缘由
- [ ] 1.2 在 `AgentRunner` 类内新增静态入口 `_entry_is_tool_result(entry)`（委托模块级函数，沿用 `_parse_event_timestamp` 惰性/静态引用先例），供类内消费点调用
- [ ] 1.3 于 `tests/test_run_latency_stats.py` 新增 `_entry_is_tool_result` 的单元测试：`user` 包裹 tool_result block 判真、纯 `text` `user` 事件判假、顶层 `tool_result` 判真、多 block `user` 事件判真、非相关事件类型判假

## 2. 三处消费点切换为统一识别

- [ ] 2.1 `latency_samples_from_events`（现 runner.py:449-480）：待配对事件的判定由 `etype == "tool_result"` 改为调用 `_entry_is_tool_result`；配对语义（tool_result ts → 下一个 assistant ts，配对后清空）保持不变
- [ ] 2.2 `_run_claude` 内联读侧采样（现 runner.py:3041-3052）：`etype == "tool_result"` 分支改为 `_entry_is_tool_result(entry)`；其余采样时序不变
- [ ] 2.3 `_turn_traffic_active`（现 runner.py:1845-1891）：逐行判定 `entry.get("type") != "tool_result"` 改为 `not _entry_is_tool_result(entry)`；窗口/mtime 回退语义不变，更新其 docstring 口径描述
- [ ] 2.4 校验 `bin/analyze_run_latency.py` 无需改代码即可经 `latency_samples_from_events` 获益（若发现其自带独立事件解析则一并切换；预期无需改动）

## 3. 观测自检与空样本文案

- [ ] 3.1 `format_latency_summary`（现 runner.py:516-533）：0 样本分支文案由「0 rounds（无 timestamp 样本，旧转录跳过）」改为中性可诊断文案（不归因于输入文件/旧转录）
- [ ] 3.2 `_run_claude` finally 延迟摘要块（现 runner.py:3204-3219）：在已算出 `stats` 后，若 `stats["rounds"] == 0` 且 `turn_count[0] > 0`，输出 WARNING 日志（含 run_id、`latency_rounds=0`、`turn_count` 数值，明示「延迟观测疑似失明」）；仅在 `rounds==0 且 turn_count==0` 时不告警。MUST 仅日志，不写 admin_alerts
- [ ] 3.3 确认自检告警不阻断 run 终态与既有摘要日志（包裹在既有 try/except 内，异常降级不影响收口）

## 4. 测试与验证

- [ ] 4.1 `tests/test_run_latency_stats.py` 新增真实形态用例：以 `user` 事件包裹 `tool_result` block（带 ISO timestamp）+ 后续 `assistant`（带 ISO timestamp）构造序列，断言 `latency_samples_from_events` 样本数 > 0 且值正确；断言纯 `text` `user` 事件不产生样本
- [ ] 4.2 `tests/test_run_latency_stats.py` 新增自检用例：驱动 `_run_claude`（fake Popen 产出仅 assistant 事件、无 tool_result）断言 WARNING 含「失明」语义且 rounds=0；再构造 rounds=0 且 turn_count=0 断言不告警
- [ ] 4.3 `tests/test_turn_limit_lifecycle.py` 新增/扩充用例：构造尾部窗口内真实形态 `user` 包裹 `tool_result` 事件的 run 文件，断言 `_turn_traffic_active` 判 True；对应扩充既有 `test_tool_result_traffic_only_extends` 走真实形态
- [ ] 4.4 保留既有合成 `_evt("tool_result", ...)` 用例全部通过（兼容路径回归基线）
- [ ] 4.5 运行 `python3 -m pytest tests/test_run_latency_stats.py tests/test_turn_limit_lifecycle.py -q` 全绿，并跑一次相关 runner 测试确认无回归

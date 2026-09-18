# 验证报告：fix-run-latency-toolresult-parser

> ⚠️ 本报告由框架于 2026-09-12T07:21:55Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.81M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| detect-user-wrapped-true | 正向路径（tool-result-stream-detection 场景1+4）：user 事件包裹 tool_result block（含多 block 并行回喂）统一识别为真；缺 message/message.content 的 user 事件判假（core/agent_runner/runner.py:449 _entry_is_tool_result） | pass | 0/5 | - |
| detect-text-user-false | 负向路径（tool-result-stream-detection 场景2）：纯 text user 事件（skill 加载消息形态）不得识别，且在采样序列中保持中性（不产生也不破坏配对；core/agent_runner/runner.py:480 latency_samples_from_events） | pass | 0/5 | - |
| detect-compat-and-others | 兼容+排除（tool-result-stream-detection 场景3+5）：顶层 tool_result 事件兼容识别为真；assistant/system/result/tool_progress/stderr/provider_marker 一律为假（core/agent_runner/runner.py:470） | pass | 0/8 | - |
| latency-real-shape-samples | 核心回归（run-latency-observability 真实转录场景）：真实 stream-json 形态转录（user 包裹 tool_result + ISO timestamp，无顶层 tool_result，含 skill 文本噪声与并行双 block）产出 2 轮非空样本，median/p90/max 为真实数值（修复前恒 0 rounds；core/agent_runner/runner.py:480） | pass | 0/7 | - |
| latency-single-pairing | 配对语义（tool-result-stream-detection 场景4 + run-latency-observability 统计不改变行为）：单 user 事件多 block 只计一次往返；一次配对后清空（后续 assistant 不重复计数）；缺 timestamp 跳过；纯函数不修改输入（core/agent_runner/runner.py:496） | pass | 0/5 | - |
| latency-summary-copy | 摘要文案（run-latency-observability 在线摘要场景）：非空摘要含 run_id/轮数/中位/p90/max/长尾；0 样本用中性文案「无 API 往返样本」，不得再出现「旧转录跳过」误导措辞（core/agent_runner/runner.py:550 format_latency_summary） | pass | 0/6 | - |
| runclaude-inline-sampling | 在线采样端到端（run-latency-observability 摘要可检索+失败附证据）：真实 _run_claude 读侧对 user 包裹 tool_result→assistant 配出 1 轮 4.5s 样本，摘要日志含 run_id 与 latency_rounds=1，无失明误报；失败异常拼入「\| latency:」证据（core/agent_runner/runner.py:3080/3245） | pass | 0/7 | - |
| selfcheck-blind-warn | 观测自检正向（run-latency-observability 失明告警场景）：有 assistant 轮次却 0 样本时输出 WARNING（含失明/latency_rounds=0/turn_count=2/run_id），且仅为日志（无 admin 告警通道；core/agent_runner/runner.py:3256） | pass | 0/7 | - |
| selfcheck-vacuum-silent | 观测自检空状态（run-latency-observability 真空跑场景）：无 assistant 事件（rounds=0 且 turn_count=0）时 0 样本为合理结果，不得误报失明告警（core/agent_runner/runner.py:3261） | pass | 0/3 | - |
| traffic-real-shape-active | 流量活性证据 b（turn-limit-lifecycle 工具流量续期场景）：_turn_traffic_active 对真实形态（user 包裹 tool_result，窗口内）判 True，兼容顶层形态；纯 text/缺失文件/过期时间戳判 False（core/agent_runner/runner.py:1883） | pass | 0/6 | - |
| analyze-script-real-shape | 离线脚本获益（run-latency-observability 真实转录场景离线侧）：bin/analyze_run_latency.py 复用修复后 latency_samples_from_events，对真实形态转录输出 2 rounds 非空摘要（脚本本身零改动；bin/analyze_run_latency.py） | pass | 0/6 | - |
| analyze-script-edge-cases | 离线脚本异常/空状态（run-latency-observability 事后分析容错场景）：损坏与空文件被跳过并报告且不中断批量扫描；无 timestamp 事件转录输出 0 rounds 不报错（bin/analyze_run_latency.py） | pass | 0/6 | - |
| pytest-latency-suite-green | 回归基线（tool-result-stream-detection 兼容路径 + run-latency-observability 全量）：tests/test_run_latency_stats.py 全绿——存量合成 _evt 顶层用例与新增真实形态夹具用例同过，证明兼容层未推翻既有基线 | pass | 0/3 | - |
| pytest-turnlimit-suite-green | 回归基线（turn-limit-lifecycle 续期矩阵未变）：tests/test_turn_limit_lifecycle.py 全绿——证据 b 从恒 False 恢复真实后，健康续期/无活性 kill/续期封顶/超时矩阵互不干扰行为仍符合既有矩阵语义 | pass | 0/3 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景


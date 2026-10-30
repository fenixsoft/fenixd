# 验证报告：evo-add-dsh-events-latency-timestamps

> ⚠️ 本报告由框架于 2026-10-30T11:29:35Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-30T11:29:34.373937+00:00+run-result@mtime1793359774424646308

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.14M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dsh-projection-timestamp-contract | 「投影事件带时间戳」契约测试：运行仓内用例 tests/test_dsh_projection.py::TestObservabilityTriple::test_projected_events_carry_timestamp，验证 DshEventProjector 投影产出的每条事件（assistant/user/system/result）携带数值到达时刻 timestamp、随到达序单调不减，且 dump 旁路原始行维持原样不加 timestamp 字段（实现点 core/agent_runner/harness/dsh_adapter.py:317-329，spec specs/dsh-events-latency-pairing/spec.md「投影事件带时间戳」） | pass | 0/2 | - |
| dsh-latency-pairing-samples | 「延迟配对出样本」：运行仓内用例 tests/test_run_latency_stats.py::TestDshEventLatencyPairing::test_dsh_projected_stream_yields_latency_samples，dsh 事件流夹具经真实 DshEventProjector 投影（_FakeDshClock 按预定刻度注入到达时刻）后，经 latency_samples_from_events（core/agent_runner/latency.py:132）产出 rounds=2 的延迟样本，间隔与注入一致（4.5s 正常样本 + 75.0s 停滞样本、stalls=1）——验证补时间戳后既有配对函数对 dsh 事件流出非零样本（spec「延迟配对出样本」） | pass | 0/2 | - |
| dsh-projection-behavior-probe | 独立行为探针（不依赖仓内测试，防测试弱化逃逸）：自建 10 行 dsh 事件流（session/status/text/tool_call/tool_result/final）逐行经 DshEventProjector.ingest 投影，断言全部投影事件携带 float>0 的 timestamp 且到达序单调不减、tool_result 载体投影为 2 条 user 事件、dump 旁路原始行无 timestamp 字段、投影事件流经 latency_samples_from_events 产出恰好 2 个非负样本（源码出处 core/agent_runner/harness/dsh_adapter.py:327-329、core/agent_runner/latency.py:132；探针脚本落 .history/，gitignored 临时目录） | pass | 0/7 | - |
| blind-warn-dedup-same-instance | 「不再逐 run 刷屏」：同一 AgentRunner 实例连续两连盲 run（rounds=0 且 turn_count>0）仅发 1 条失明 WARNING，且首条文案契约成立——如实归因（含「缺时间戳」/「无法配对」，不含误归因「请检查 tool_result 事件识别」）、extra 锚点 latency_rounds=0/turn_count/run_id 保留（实现点 core/agent_runner/runner.py:7075-7103；测试 tests/test_run_latency_stats.py::TestLatencyBlindWarnDedup::test_same_instance_second_blind_run_silent，spec「失明告警去重」） | pass | 0/2 | - |
| blind-warn-dedup-instance-isolation | 去重状态实例级隔离：新 runner 实例对同（harness,形态）键再次告警（去重登记随实例丢弃）——MUST NOT 模块级集合，否则同进程更早用例会把 tests/test_run_latency_stats.py:354 失明用例 primed 掉（design.md 去重实现约束；测试 tests/test_run_latency_stats.py::TestLatencyBlindWarnDedup::test_new_instance_warns_again） | pass | 0/2 | - |
| blind-warn-shape-key-isolation | 形态半边参与去重键：assistant 事件缺 timestamp 的失明形态键为 missing_timestamp（runner.py:7076-7081 三形态判定），与 no_tool_result 形态互不 primed——异常路径（缺时间戳事件流）仍能独立告警一次（测试 tests/test_run_latency_stats.py::TestLatencyBlindWarnDedup::test_missing_timestamp_shape_key） | pass | 0/2 | - |
| blind-warn-legacy-anchors-reconciliation | 任务 2.3 对账：既有失明两用例（:354 blind 断言 ≥1 条 WARNING、:387 vacuum 真空跑断言 ==0）在实例级去重+新文案下断言零改动继续通过——「失明」标记与 latency_rounds/turn_count/run_id extra 锚点未丢失（tests/test_run_latency_stats.py::TestRunClaudeIntegration::test_latency_self_check_warns_on_blind_run 与 ::test_latency_self_check_no_warn_when_vacuum_run；design.md 文案锚点约束） | pass | 0/3 | - |
| blind-warn-source-contract-probe | 源码静态契约探针：对 core/agent_runner/runner.py 失明 WARNING 发射点逐项 grep 断言——文案含「缺时间戳」如实归因、含「失明」标记锚点、不再含误归因「请检查 tool_result 事件识别」、去重状态为实例属性 self._latency_blind_warned_keys（非模块级集合；源码出处 core/agent_runner/runner.py:7087-7103），与行为测试互补防回归 | pass | 0/5 | - |
| dsh-latency-test-files-regression | 回归点：本 SPEC 两份交付测试文件全量通过（tests/test_dsh_projection.py + tests/test_run_latency_stats.py，当前基线 54 用例），覆盖配对函数异常路径不回归——缺 timestamp 事件跳过（test_missing_timestamp_skipped）、ISO 时间戳解析、负差值剔除、真空跑不告警等既有契约（回归对比：改动前后两文件应全绿） | pass | 0/2 | - |

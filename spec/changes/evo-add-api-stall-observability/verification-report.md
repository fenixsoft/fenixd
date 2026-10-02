# 验证报告：evo-add-api-stall-observability

> ⚠️ 本报告由框架于 2026-10-02T20:40:57Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-02T20:40:56.563210+00:00+run-result@mtime1790973656592781972

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.49M |
| 本链增量 Token（输出） | 0.02M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| stall-warn-threshold-constant | 停滞告警常量单源与语义分离探针：latency.py 模块级常量 STALL_ROUND_WARN_SECONDS=120.0（期内告警线）在场，runner.py re-export 同值（不另立常量）；统计口径 LATENCY_STALL_SECONDS=60.0 与判停计入线 RUN_STALL_ROUND_SECONDS=120.0 均未被本能力改动——三常量同值不同义、各自独立（design 决策 1：严禁合并复用）。探针 stdout 只输出 JSON 结果对象。tasks.md 1.1（出处 core/agent_runner/latency.py:36、core/agent_runner/runner.py:65、tests/test_run_latency_stats.py::TestStallRoundWarn::test_stall_round_warn_constant_value） | pass | 0/5 | - |
| stall-warn-over-threshold-warning | 超阈值样本触发期内时点 WARNING：251.1s 样本（>120s）在飞采样点于样本完成时点产出恰一条 WARNING（component=agent_runner，含 run_id 与样本秒数 :.1f 文本、轮序号 latency_round=1、event=api_round_stall），样本照常进入既有样本序列。spec.md Scenario「超阈值样本触发 WARNING」。命令只带 -v 不带 -q（pytest 9 中 -q 覆盖 -v 会吞掉用例级 PASSED 行），断言文案 <nodeid> PASSED 来自 -v 输出真实形态（本机实测同命令输出该形态）。tasks.md 1.2（出处 core/agent_runner/runner.py:5018-5032、tests/test_run_latency_stats.py::TestStallRoundWarn::test_over_threshold_sample_warns） | pass | 0/2 | - |
| stall-warn-below-threshold-silent | 阈值内样本保持静默与无效测量双静默：119.9s 边界内与恰 120.0s（严格 > 比较）样本全 run 零 WARNING 且样本照常入序列（2 rounds）；timestamp 缺失/负差值无效测量既不产样本（0 rounds）也不触发 WARNING。spec.md Scenario「阈值内样本保持静默」。断言文案来自 -v 输出真实形态（本机实测）。tasks.md 1.2（出处 core/agent_runner/runner.py:5018、tests/test_run_latency_stats.py::TestStallRoundWarn::test_boundary_and_below_threshold_silent 与 ::test_invalid_measurement_no_sample_no_warn） | pass | 0/3 | - |
| stall-warn-pure-readside-stats-unchanged | 纯读侧：触发 WARNING 的 run 其 run 末延迟摘要与纯函数 latency_stats(latency_samples_from_events(events)) 对同一事件序列的计算逐字段一致（error 摘要含 " \| latency: run …: 2 rounds, … max 251.1s"），告警样本序数为第 2 个有效样本——告警不改变样本序列与统计结果。spec.md「AND 该样本仍照常进入既有样本序列，latency_stats 结果与不加告警时逐字段一致」。断言文案来自 -v 输出真实形态（本机实测）。tasks.md 2.1（出处 tests/test_run_latency_stats.py::TestStallRoundWarn::test_stats_unchanged_by_warning） | pass | 0/2 | - |
| stall-accounting-run-metrics-fields | 停滞指标随 run_metrics 两处落点入账：带停滞样本 run（3 有效样本、2 个 >60s、最长 251.1s）收尾后，档案 run_metrics 行含 latency_rounds=3/latency_stalls=2/latency_max≈251.1，既有字段（run_id/turns/input_tokens 等 9 键）不动；仍恰一条 run_metrics 行且位于 error 终态行之后（行序契约不变）；daemon 侧 metric_type=run_metrics 内联日志（不经过 _log_run_metrics 的正常收尾形态）context 恰一条且同名字段同值——同一 stats 单一真源。spec.md Scenario「有停滞样本的 run 两处落点均含字段」。断言文案来自 -v 输出真实形态（本机实测）。tasks.md 1.3①②（出处 core/agent_runner/runner.py:5457-5498、tests/test_run_stall_accounting.py::TestStallMetricsAccounting::test_stall_run_metrics_line_fields） | pass | 0/2 | - |
| stall-accounting-zero-sample-fallback | 零样本 run 字段安全回退：启动即失败（无任何有效样本）的 run 收尾后，档案 run_metrics 行与 daemon 侧 context 均回退 latency_rounds=0/latency_stalls=0/latency_max=None，不抛异常、不阻断收尾，正常失败路径 error 终态行仍为文件末行（既有行序不变）。spec.md Scenario「零样本 run 字段安全回退」。断言文案来自 -v 输出真实形态（本机实测）。tasks.md 1.3（出处 core/agent_runner/runner.py:5396 stall_latency 初始零样本回退、tests/test_run_stall_accounting.py::TestStallMetricsAccounting::test_zero_sample_run_fields_fallback） | pass | 0/2 | - |
| stall-accounting-crash-path-defaults | 轮询环崩溃路径字段缺省不抛：poll 环异常（TypeError）→ error 终态行照常先写，run_metrics 行照常追加于终态行之后（权威契约形态），字段缺省走同一零样本回退（0/0/None）不抛；daemon 侧内联日志同样落盘、字段缺省不抛。spec.md「AND 崩溃路径（轮询环异常 → error 终态）下 run_metrics 行仍照既有契约追加，字段缺省不抛」。断言文案来自 -v 输出真实形态（本机实测）。tasks.md 2.2（出处 core/agent_runner/runner.py:5448-5456 注记契约、tests/test_run_stall_accounting.py::TestStallMetricsAccounting::test_poll_loop_crash_metrics_defaults） | pass | 0/2 | - |
| stall-observability-terminal-contract-regression | 回归点（行序契约权威测试）：既有权威测试 test_run_claude_poll_loop_crash_writes_error_terminal（spec.md AND 子句引用的行序口径——恰一条 run_metrics 行且位于终态行之后、末行契约读侧口径）在新三字段入账后仍通过，证明加法字段无破坏（design 风险项：严格 schema 消费者不被未知字段拒绝）。断言文案来自 -v 输出真实形态（本机实测该 node id 全形态输出 PASSED）。tasks.md 1.3（出处 tests/test_daemon_lifecycle_races.py:448 TestRuntimeDanglingRunSweep::test_run_claude_poll_loop_crash_writes_error_terminal） | pass | 0/2 | - |
| stall-observability-full-suite-regression | 回归点（交付测试文件全量）：本 SPEC 两个测试交付物 tests/test_run_latency_stats.py（扩展：既有 tool_result 识别/样本提取/统计摘要用例 + 新增 TestStallRoundWarn 五用例）与 tests/test_run_stall_accounting.py（新增三用例）合并运行整体通过（本机实测同命令摘要行「36 passed, 7 warnings in 0.35s」形态）——无既有用例回归、无新增用例失败。tasks.md Deliverables（出处 spec/changes/evo-add-api-stall-observability/tasks.md、两测试文件）。此场景只带 -q（安静形态）并按其真实摘要「N passed」断言，不与 -v 并列（pytest 9 中 -q 覆盖 -v） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 9 个（第 1 轮）。

- 首轮写入 9 个场景


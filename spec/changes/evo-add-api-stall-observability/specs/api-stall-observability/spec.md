# Spec: add-api-stall-observability

## ADDED Requirements

### Requirement: run 期内单次 API 往返停滞的时点记录

runner 的在飞延迟采样点（`_run_claude` 流式循环旁路，`core/agent_runner/runner.py` 内联采样，样本口径 = tool_result→下一 assistant 间隔、与 `core/agent_runner/latency.py` 单源一致）在单次样本超过 `STALL_ROUND_WARN_SECONDS`（新模块级常量，120.0 秒）时，须即时输出一条 WARNING 日志，至少含 run_id、样本秒数（1 位小数）与轮序号（该样本在有效样本序列中的序数）。

#### Scenario: 超阈值样本触发 WARNING

- **WHEN** 某 run 的某次 tool_result→assistant 间隔为 251.1s（> 120s）
- **THEN** 在该 assistant 事件处理时点（非 run 收尾）输出一条 WARNING 日志，含 run_id 与 "251.1"
- **AND** 该样本仍照常进入既有样本序列，`latency_stats` 结果与不加告警时逐字段一致

#### Scenario: 阈值内样本保持静默

- **WHEN** 某 run 的全部样本均 ≤ 120s（含 119.9s 边界内样本）
- **THEN** 全 run 期间不输出任何停滞 WARNING
- **AND** timestamp 缺失/负差值等无效测量不产生样本也不触发 WARNING

### Requirement: 停滞指标随 run_metrics 入账

run 收尾时，档案 run_metrics 记录（`append_run_line` 的 `type: run_metrics` 行）与 daemon 侧 run metrics 结构化日志（`metric_type: run_metrics`）均须新增 `latency_rounds`（有效样本数）、`latency_stalls`（>60s 样本数）、`latency_max`（最长样本秒）三个字段，取值复用 run 末延迟摘要已计算的同一 `latency_stats` 结果（单一真源，禁止重复采样或二次计算）。

#### Scenario: 有停滞样本的 run 两处落点均含字段

- **WHEN** 某 run 产出 17 个有效样本、其中 4 个 >60s、最长 251.1s
- **THEN** 档案 run_metrics 行含 `latency_rounds=17`、`latency_stalls=4`、`latency_max=251.1`
- **AND** 同 run 的 daemon 侧 run metrics 日志 context 含同名字段同值
- **AND** 该行仍恰为一条 run_metrics 行、位于终态行之后（既有行序契约不变，`tests/test_daemon_lifecycle_races.py::test_run_claude_poll_loop_crash_writes_error_terminal` 口径）

#### Scenario: 零样本 run 字段安全回退

- **WHEN** 某 run 无任何有效样本（启动即失败/解析器零配对）
- **THEN** 两个字段落点照常写入 `latency_rounds=0`、`latency_stalls=0`、`latency_max=None`（或省略 latency_max），不抛异常、不阻断 run 收尾
- **AND** 崩溃路径（轮询环异常 → error 终态）下 run_metrics 行仍照既有契约追加，字段缺省不抛

### Requirement: 纯读侧与告警纪律

本能力的全部记录动作 MUST 为纯读侧旁路：不改变流式事件处理时序、不向 run jsonl 注入新事件类型、不终止/重启进程、不重派、不接入独立人工告警与 admin 唤醒（对齐 `spec/knowledge/domains/cost-observability/run-latency-observability.md` 的告警纪律），不新增配置键。

#### Scenario: 停滞记录不改变 run 终态与调度

- **WHEN** 某 run 连续出现多条 >120s 样本（如 85.1/86.3/123.0/251.1s 四次停滞）
- **THEN** run 仍按 CLI 子进程自然终态收尾（success/failure 均不因停滞记录改变）
- **AND** 无任何重派/取消/kill 动作被触发，无人工告警产生
- **AND** run jsonl 事件类型集合与记录前一致（无新增事件类型）
# per-agent-timeout-override

## ADDED Requirements

### Requirement: run_timeout_seconds 按 agent_type 覆盖

新增配置键 `agents.timeout_overrides`（映射：agent_type → 秒数）。run 生效超时的解析顺序 MUST 为：`agents.timeout_overrides.<agent_type>` 存在且合法时取覆盖值，否则回退 `agents.run_timeout_seconds` 全局默认。覆盖 MUST 适用于全部七类 agent run：implementer、verifier、planner-plan、planner-judge、fast-track、repair、administrator（后两者经 `_execute_agent` 与 `_run_claude` 统一路径生效）。

#### Scenario: 覆盖值对指定类型生效

- **WHEN** 配置 `agents.timeout_overrides: {planner-plan: 2700}` 且全局 `run_timeout_seconds: 9000`，planner-plan 类 run 启动
- **THEN** 该 run 的超时 deadline 为 started_at + 2700 秒；同期的 implementer run deadline 仍为 9000 秒

#### Scenario: 未配置类型回退全局默认

- **WHEN** 配置仅含 `agents.timeout_overrides: {planner-plan: 2700}`，verifier 类 run 启动
- **THEN** verifier run 的超时 deadline 按全局 9000 秒生效

#### Scenario: 非法覆盖值护栏

- **WHEN** `agents.timeout_overrides` 含非法值（非正整数、未知 agent_type、或低于 300 秒）
- **THEN** daemon 打 ERROR 日志说明该键被忽略并回退全局默认，其余合法键正常生效；进程不得崩溃

### Requirement: supervision 派生值按生效超时联动

supervision 的 extension 总额与 absolute_max 兜底 MUST 按该 agent type 的生效超时（覆盖后）派生：`absolute_max_seconds` 配置值低于 生效超时 + max_extensions × extension_seconds 时按后者抬升兜底（沿用既有护栏语义）；`admin_monitor` 的 stuck 阈值派生（run_timeout + 宽限）MUST 取全局默认值语义不变。

#### Scenario: absolute_max 低于覆盖值时抬升

- **WHEN** 某类型生效超时被覆盖为 7200，配置 `max_extensions: 2`、`extension_seconds: 1800`、`absolute_max_seconds: 9000`
- **THEN** 该类型 run 的 absolute_max 实际按 7200 + 3600 = 10800 秒兜底生效，并留 ERROR/WARNING 级配置告警日志

#### Scenario: stuck 阈值语义不变

- **WHEN** `agents.timeout_overrides` 存在任一覆盖键
- **THEN** admin_monitor 的 stuck 阈值仍按全局 `run_timeout_seconds` + 宽限派生，不随单个类型的覆盖值变化

### Requirement: 监督器内部 judge 超时配置化

`liveness.py` 的推进判定 judge 子进程超时 MUST 从配置读取：`agents.timeout_overrides.supervision-judge`，缺省回退 120 秒常量；该值不参与 absolute_max 派生。

#### Scenario: supervision judge 超时可配置

- **WHEN** 配置 `agents.timeout_overrides: {supervision-judge: 240}`
- **THEN** supervision 推进判定 judge 的 subprocess timeout 为 240 秒；未配置时为 120 秒

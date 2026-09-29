<!-- knowledge: capability=per-agent-timeout-override rev=1 sources=spec/archive/2026-09-10-run-lifecycle-hardening -->

# 按 Agent 类型超时覆盖

`agents.timeout_overrides` 的覆盖解析、护栏与 supervision 派生联动：不同 agent 类型的 run 超时可各别配置。

## 现行规则

- 覆盖解析：配置键 `agents.timeout_overrides`（映射：agent_type → 秒数）。run 生效超时的解析顺序：`agents.timeout_overrides.<agent_type>` 存在且合法时取覆盖值，否则回退 `agents.run_timeout_seconds` 全局默认。覆盖适用于全部七类 agent run：implementer、verifier、planner-plan、planner-judge、fast-track、repair、administrator（经 `_execute_agent` 与 `_run_claude` 统一路径生效）。
- 非法值护栏：覆盖值非法（非正整数、未知 agent_type、低于 300 秒）时打 ERROR 日志说明该键被忽略并回退全局默认，其余合法键正常生效，进程不崩溃。
- supervision 派生联动：extension 总额与 `absolute_max` 兜底按该类型的生效超时（覆盖后）派生——`absolute_max_seconds` 配置值低于「生效超时 + max_extensions × extension_seconds」时按后者抬升兜底（沿用既有护栏语义），并留 ERROR/WARNING 级配置告警日志。
- stuck 阈值不联动：`admin_monitor` 的 stuck 阈值派生（run_timeout + 宽限）取全局默认值语义，不随单个类型的覆盖值变化。
- supervision judge 超时配置化：`liveness.py` 推进判定 judge 子进程超时从 `agents.timeout_overrides.supervision-judge` 读取，缺省回退 120 秒常量；该值不参与 `absolute_max` 派生。

## 溯源

- [2026-09-10 run-lifecycle-hardening](spec/archive/2026-09-10-run-lifecycle-hardening/) — 固化按 agent_type 超时覆盖与七类 run 适用、非法值护栏、supervision extension/absolute_max 派生联动（stuck 阈值不联动）与 supervision-judge 超时配置化

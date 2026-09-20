# Spec Delta: robustness

## ADDED Requirements

### Requirement: 超时监督判定对门面契约漂移免疫

`core/agent_runner/liveness.py` 的 `_supervision_deadline_action` 在解析生效 run 超时时，
系统 SHALL 保证「门面未给出可用数值」不导致判定崩溃：门面
`self._pm._effective_run_timeout(agent_type)` 返回 `None`、返回非数值、返回非正数，
或调用本身抛出异常时，该函数 MUST 回退
`core.config.RUN_TIMEOUT_FALLBACK_SECONDS`（9000）作为 `run_timeout`（与
`ConfigLoader.supervision_floor` 的派生口径同源，MUST NOT 手写字面常数），
MUST NOT 让异常逃逸出本函数。

兜底发生时 MUST 留一条 WARNING 日志（component `agent_runner`，含 `agent_type`
与收到的原始值），保证契约漂移可归因。

正常路径（门面返回有效数值）的 `run_timeout` 取值 MUST 与修复前逐位一致。

#### Scenario: 门面返回 None 时判定不崩溃
- **WHEN** 门面 `_effective_run_timeout(agent_type)` 返回 `None`（或非数值 / 非正数），
  且 deadline 已到点、`extensions_used=0`
- **THEN** `_supervision_deadline_action` MUST 不抛异常，按兜底 `run_timeout=9000`
  继续封闭矩阵判定（派生 `absolute_max = 9000 + 2×1800 = 12600`），并返回
  `{"action": "kill"|"extend", ...}` 之一
- **AND** MUST 记录含 `agent_type` 的 WARNING 日志

#### Scenario: 门面调用抛异常时判定不崩溃
- **WHEN** 门面 `_effective_run_timeout(agent_type)` 调用本身抛出 `TypeError` /
  `ValueError` / `AttributeError`（进程表或配置层故障）
- **THEN** 该异常 MUST 被吞并回退为兜底值，判定继续；异常 MUST NOT 冒泡到
  `core/agent_runner/runner.py` 的轮询环（否则一次 deadline 判定升级为
  `run thread crashed` 终态）

#### Scenario: 有效期路径数值不变
- **WHEN** 门面返回有效数值（如 per-agent 覆盖 9000 或全局回退值）
- **THEN** `run_timeout` 取值与修复前完全一致，`absolute_max_seconds` 兜底与
  ERROR 文案数值不变（既有 `tests/test_supervision_timeout_consistency.py` 与
  `tests/test_run_lifecycle_governance.py` 用例零回归）

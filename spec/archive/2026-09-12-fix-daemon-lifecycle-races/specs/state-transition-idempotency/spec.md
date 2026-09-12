# state-transition-idempotency

## ADDED Requirements

### Requirement: 幂等自迁移降级

`transition()` 对 `new_status == old_status` 的调用 SHALL 视为幂等自迁移：打 INFO 日志（含 spec 名与状态值）并直接返回 True，不进入 `VALID_TRANSITIONS` 拒绝分支、不记 ERROR。`transition_gate()` 同型处理。真实非法迁移（如 `implemented→verified`）仍记 ERROR。

#### Scenario: pushed→pushed 幂等通过

- **WHEN** 已处于 pushed 终态的 spec 再次调用 `transition(spec, "pushed")`
- **THEN** 打 INFO 幂等日志、返回 True，无 ERROR 告警产生

#### Scenario: 真实非法迁移仍报 ERROR

- **WHEN** spec 处于 implemented 状态调用 `transition(spec, "verified")`
- **THEN** 仍打 ERROR「Invalid transition」并返回 False

#### Scenario: 调用点返回值依赖核查

- **WHEN** 实现幂等短路时核查全库 `transition(` / `transition_gate(` 调用点
- **THEN** 依赖返回 False 阻断重复副作用的调用点（如 `engine.py` total_duration 覆盖防护）改为前置状态判断或登记 findings 说明幂等覆盖无害，不静默改变行为

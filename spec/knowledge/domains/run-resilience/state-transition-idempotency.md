<!-- knowledge: capability=state-transition-idempotency rev=1 sources=spec/archive/2026-09-12-fix-daemon-lifecycle-races -->

# 状态迁移幂等

状态机对同状态重复迁移（old==new）的幂等降级：ERROR 告警只留给真实非法迁移，同状态并发双路径不再产生假告警。

## 现行规则

- `transition()` 对 `new_status == old_status` 的调用视为幂等自迁移：打 INFO 日志（含 spec 名与状态值）并直接返回 True，不进入 `VALID_TRANSITIONS` 拒绝分支、不记 ERROR；`transition_gate()` 同型处理。
- 真实非法迁移（如 implemented→verified）仍记 ERROR「Invalid transition」并返回 False。
- 依赖返回 False 阻断重复副作用的调用点（如 total_duration 覆盖防护）以前置状态判断实现阻断，或登记 findings 说明幂等覆盖无害；不得依赖幂等短路后的 False 返回值。

## 溯源

- 2026-09-12 fix-daemon-lifecycle-races（spec/archive/2026-09-12-fix-daemon-lifecycle-races） — 确立幂等自迁移 INFO 降级：pushed→pushed 双路径并发不再产生假 ERROR 告警，ERROR 保留给真实非法迁移

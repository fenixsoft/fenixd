<!-- knowledge: capability=dispatch-dependency-wakeup rev=1 sources=spec/archive/2026-09-18-fix-dispatch-wakeup-gap -->

# 依赖满足后的派发唤醒

依赖 SPEC 转入接受态时对等待中的 dependents 做定向重评与入队，消除「依赖已满足却空等一个扫描周期」的调度缺口。

## 现行规则

- 某 SPEC 转入依赖闸门接受态（`done` / `pushed` / `implemented` / `verified`，单源常量 `DEPENDENCY_ACCEPTED_STATUSES`）时，系统对所有把它声明为 `depends_on` 的等待中 SPEC 补一次依赖重评。
- 重评复用既有 `_dependencies_satisfied` 判据（同一接受态集合、同一 STATE.md 读取口径），不另立判据。
- 重评通过且该 SPEC 处于可派发态时立即入队派发，不等下一轮 `full_scan`。
- 定向唤醒不引入新的轮询定时器；不缩短或改动 `schedule.poll_interval_minutes` 与全量扫描的触发源；不改动优先级、并发与预算闸门的判定口径。
- 依赖未满足时不唤醒：依赖处于 `blocked` 或仍停留在推进态（如 implementing）时，dependent 保持等待态。
- 无 dependents 时零副作用：不产生额外派发、状态写入或错误日志。
- 幂等与去重：dependent 已有活跃派发或已在飞派发中时，其依赖再转入接受态不重复派发。
- `depends_on` 指向 STATE.md 中不存在的名字时，按既有口径判为不满足（记 WARNING），不因定向唤醒路径派发。

## 溯源

- 2026-09-18 2026-09-18-fix-dispatch-wakeup-gap — 新增依赖定向唤醒：依赖满足是别的 SPEC 的状态变化，原事件机制不会为等待中的 SPEC 产生事件，实证最坏空等 25 分钟；本能力使等待时间从「最坏一个扫描周期（缺省 30 分钟）」降为「事件到达即唤醒」。

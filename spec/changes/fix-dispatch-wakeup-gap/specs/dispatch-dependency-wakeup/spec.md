# Spec Delta: dispatch-dependency-wakeup

## ADDED Requirements

### Requirement: 依赖满足时定向唤醒等待中的 dependents

当某个 SPEC 转入依赖闸门的接受态（`done` / `pushed` / `implemented` / `verified`）时，系统 MUST 对所有把它声明为 `depends_on` 的等待中 SPEC 补一次依赖重评。重评 MUST 复用既有 `_dependencies_satisfied` 判据（同一接受态集合、同一 STATE.md 读取口径），不得另立判据。重评通过且该 SPEC 处于可派发态时 MUST 入队派发，MUST NOT 等待下一轮 `full_scan`。

定向唤醒 MUST NOT 引入新的轮询定时器，MUST NOT 缩短或改动 `schedule.poll_interval_minutes` 与全量扫描的触发源，MUST NOT 改动优先级、并发与预算闸门的判定口径。

#### Scenario: 依赖转入接受态后 dependent 立即入队

- **WHEN** SPEC A 声明 `depends_on: B`，B 处于 implementing（非接受态）导致 A 的派发被依赖闸门跳过并出队，随后 B 转为 pushed
- **THEN** 系统 MUST 在 B 该次状态变更的处理中重评 A 的依赖并立即入队派发 A，MUST NOT 等到下一轮 full_scan

#### Scenario: 依赖未满足时不提前唤醒

- **WHEN** SPEC A 声明 `depends_on: B`，B 转为 blocked 或仍停留在 implementing
- **THEN** 系统 MUST NOT 唤醒 A（不重评通过、不入队），A 保持等待态

#### Scenario: 无 dependents 时零副作用

- **WHEN** 某 SPEC 转入接受态，但版本库中没有任何 SPEC 声明依赖它
- **THEN** 系统 MUST NOT 产生额外派发、状态写入或错误日志

#### Scenario: 幂等与去重

- **WHEN** 某 dependent 已具备派发条件且已有活跃派发或已在飞派发中，其依赖再次转入接受态
- **THEN** 系统 MUST NOT 重复派发该 dependent

#### Scenario: 依赖声明不存在时不唤醒

- **WHEN** 某 SPEC 的 `depends_on` 指向一个在 STATE.md 中不存在的名字
- **THEN** 系统 MUST 按既有 `_dependencies_satisfied` 口径判为不满足（记 WARNING），MUST NOT 因定向唤醒路径而派发它

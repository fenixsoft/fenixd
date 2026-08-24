## ADDED Requirements

### Requirement: 高优先级任务先执行

调度器 SHALL 按 SPEC priority（数值越小优先级越高）派发 Agent：每次派发 SHALL 面向当前就绪任务中优先级最高（数值最小）的档位。当更高优先级任务就绪时，SHALL 优先于已就绪的低优先级任务被派发；已在运行的 Agent 不被抢占（kill/中断），但低优先级任务不得在更高优先级任务仍就绪或运行时被新派发。

#### Scenario: 高低优先级同时就绪时高优先级先派发
- **WHEN** `priority=1` 的 SPEC-A 与 `priority=5` 的 SPEC-B 同时处于就绪态，无 Agent 在运行
- **THEN** 调度器 SHALL 先派发 SPEC-A 的 implementer，SPEC-B 的 implementer 在 SPEC-A 完成前不启动

#### Scenario: 高优先级到达时不抢占正在运行的低优先级
- **WHEN** `priority=5` 的 SPEC-B 正在运行，`priority=1` 的 SPEC-A 随后进入就绪态
- **THEN** 已运行的 SPEC-B 不被终止；SPEC-A 在 SPEC-B 排空后启动，且期间不得有新的低优先级任务被派发

### Requirement: 同一优先级任务可并行执行

调度器 SHALL 允许同一优先级档内的多个任务并行执行，并行数量受「并行度」（`agents.max_concurrent`）上限约束。同一档内 SHALL 保持先到先服务的派发顺序。

#### Scenario: 并行度 2 时同优先级任务并行运行
- **WHEN** 并行度为 2，三个 `priority=3` 的 SPEC 均就绪且无 Agent 运行
- **THEN** 调度器 SHALL 同时派发其中两个 SPEC 的 implementer，第三个在任一槽位释放后启动

#### Scenario: 并行度上限不被突破
- **WHEN** 并行度为 2，同一优先级有 4 个就绪任务
- **THEN** 任意时刻正在运行的 Agent 数不超过 2

### Requirement: 不同优先级任务不并行

调度器 SHALL 保证不同优先级的任务不并行运行：当有其它优先级的 Agent 正在运行时，SHALL 不派发新优先级档的任务（即使并行度有空闲槽位）。新档位 SHALL 仅在当前运行档位全部排空后才启动。

#### Scenario: 槽位空闲但存在运行中的不同优先级任务时不派发
- **WHEN** 并行度为 2，一个 `priority=1` 的 Agent 正在运行（占用 1 个槽位），`priority=5` 的 SPEC 就绪
- **THEN** 空闲槽位不被 `priority=5` 的任务占用，其等待 `priority=1` 档全部排空后再启动

#### Scenario: 同档任务在运行期间允许补齐并行度
- **WHEN** 并行度为 2，一个 `priority=2` 的 Agent 正在运行，另有同 `priority=2` 的 SPEC 就绪
- **THEN** 该同优先级 SPEC 可被派发以利用空闲槽位（不同优先级不并行仅约束跨档）

### Requirement: verifier 紧随其 implementer 派发

当某 SPEC 的 implementer 完成后，其 verifier SHALL 在同一优先级档内按先到先服务紧随派发，保证验证顺序不因优先级调度而回退。

#### Scenario: implementer 完成后 verifier 同档紧随
- **WHEN** 某 SPEC 的 implementer 成功完成，其 verifier 就绪
- **THEN** 该 verifier 携带与 implementer 相同的 SPEC priority 入队，在同一档内按先到先服务被派发，不被其它档位插队

### Requirement: 向后兼容

当所有就绪 SPEC 的 priority 相同（含全部使用默认值 5）时，调度行为 SHALL 等价于按入队顺序、以并行度为上限的并发执行（即现状 FIFO + 并发上限语义）。旧配置文件无需新增任何字段即可使用新调度器。

#### Scenario: 全部同优先级时按入队顺序并行
- **WHEN** 多个 SPEC 均为默认 `priority=5`，并行度为 2
- **THEN** 按入队先后顺序，最多 2 个并发执行，无额外阻塞或乱序

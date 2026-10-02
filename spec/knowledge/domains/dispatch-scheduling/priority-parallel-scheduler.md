<!-- knowledge: capability=priority-parallel-scheduler rev=1 sources=spec/archive/2026-09-02-add-parallelism -->

# 优先级并行调度

派发队列的优先级感知调度：高优先级先派发、同档并行至并行度上限、档间按宽松并发口径放行、不抢占。

## 现行规则

- 调度按 SPEC priority（数值越小优先级越高）派发：每轮派发队列中最高优先级的合法就绪条目。
- 宽松并发口径：任务 X 可派发当且仅当不存在比 X 更高优先级（数值更小）的活动任务（即 `min(active_priorities) >= X` 的优先级数值）——有 P6 在跑时 P5 可并发入池、P7 不行；满足该规则时不同优先级档位亦可并发。
- 同一优先级档内多个任务可并行执行，并行数量受并行度（`agents.max_concurrent`）上限约束；任意时刻正在运行的 Agent 数不超过并行度。
- 同档内保持先到先服务的派发顺序。
- 不抢占：高优先级任务到达时，已在运行的 Agent 不被终止或中断。
- verifier 紧随其 implementer 派发：implementer 完成后，其 verifier 携带与 implementer 相同的 SPEC priority 入队，在同一档内按先到先服务派发，不被其它档位插队（验证顺序不因优先级调度而回退）。
- bug-found 打回形成的僵尸 holding 态条目不占并发槽位。
- 向后兼容：所有就绪 SPEC 的 priority 相同（含全部使用默认值 5）时，调度行为等价于按入队顺序、以并行度为上限的并发执行（FIFO + 并发上限）；旧配置文件无需新增任何字段。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：严格优先级调度同档补齐；宽松并发口径允许低档在跑时相邻高档并发入池，bug-found 僵尸 holding 态不占并发
- 2026-09-02 2026-09-02-add-parallelism（spec/archive/2026-09-02-add-parallelism） — 建立优先级感知的并行调度：队列条目携带 priority、同档并行至并行度上限、verifier 由队列物理插队改为与 implementer 同档排队、全同优先级时退化 FIFO+并发上限（其档间严格串行口径后被宽松并发口径取代）。

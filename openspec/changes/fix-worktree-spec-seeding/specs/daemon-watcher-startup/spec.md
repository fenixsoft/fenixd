## ADDED Requirements

### Requirement: Agent 派发不阻塞事件处理线程
`core/pm_engine.py` 的 Agent 派发（`_process_queue` 及 `handle_event` 调用链）MUST 以异步方式执行：每次运行在独立 worker 线程中启动，派发调用在启动线程后立即返回，不得阻塞调用线程（含 daemon 启动时的初始 `full_scan`、EventBus watcher 事件处理、periodic scan）。因此 `FenixDaemon.start()` 即便在初始扫描派发了实现 Agent，MUST 仍能继续执行 `event_bus.start()` 并启动 watcher/scanner 线程。

#### Scenario: 启动时派发不阻塞 watcher 启动
- **WHEN** daemon 启动时存在可派发的 SPEC（drafted/ready）且派发了实现 Agent
- **THEN** `full_scan` 派发后立即返回，`event_bus.start()` 正常启动 watcher 与 periodic scanner 线程（进程线程数 ≥3），后续 STATE.md 变更（新增 SPEC、状态转换）持续产生事件

#### Scenario: 运行期事件处理不被 Agent 阻塞
- **WHEN** watcher 检测到 STATE.md 变更并派发新的 Agent，同时已有 Agent 在运行
- **THEN** watcher 线程派发后立即返回，可继续检测后续变更，不被运行中的 Agent 阻塞

### Requirement: 多 Agent 按 max_concurrent 并发执行
Agent 运行 MUST 以 `agents.max_concurrent`（配置项，默认 2）为并发上限并行执行；队列中有多个待运行 SPEC 时，MUST 在不超过上限的前提下同时运行多个 Agent（实现/验证），而不是串行逐个执行。并发计数（`_active_runs`）与运行队列（`_run_queue`）的读写 MUST 由锁保护，避免竞态与超发。

#### Scenario: 并发运行多个 SPEC
- **WHEN** 运行队列中有 2 个以上待运行 SPEC，且 `max_concurrent=2`
- **THEN** 同时有 2 个 Agent 在运行（`_active_runs==2`），完成一个后自动补位下一个

#### Scenario: 并发不超过上限
- **WHEN** 队列持续有任务且 `max_concurrent=2`
- **THEN** 任意时刻运行中的 Agent 数不超过 2，`_active_runs` 精确增减

### Requirement: 共享状态线程安全
Agent 派发线程化后，`pm_engine` 的共享可变状态（`_run_queue`、`_active_runs`、以及 Agent 完成后对状态机结果的处理）MUST 线程安全：队列与计数的读写加锁；同一 SPEC 的重复调度由既有防重入守卫（`_handling_events` / `_spec_locks`）保证；STATE.md 的写入继续由 `StateMachine.write_all` 的文件锁保护。不得因并发引入状态推进的重复或丢失。

#### Scenario: 并发下状态推进不重复不丢失
- **WHEN** 多个 Agent 并发完成并各自推进 SPEC 状态
- **THEN** 每个 SPEC 的状态转换恰好发生一次（合法转换校验照常），无并发重复推进或丢失

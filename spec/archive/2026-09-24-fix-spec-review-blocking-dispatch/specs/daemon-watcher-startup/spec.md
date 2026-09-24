## MODIFIED Requirements

### Requirement: Agent 派发不阻塞事件处理线程

Agent 派发（`_process_queue` 及 `handle_event` 调用链）MUST 以异步方式执行：每次运行在独立 worker 线程中启动，派发调用在启动线程后立即返回，不得阻塞调用线程。本约束 MUST 覆盖**全部** agent 类型——implementer、fast-track、verifier、repair、**spec-review** 一视同仁，MUST NOT 存在「某一类 agent 在调用栈上同步执行」的例外。

`FenixDaemon.start()` 即便在初始扫描派发了实现 Agent 或评审 Agent，MUST 仍能继续执行并**进入主循环**——主循环内的文件信号消费者（`_check_admin_invoke_requests` / `_check_cancel_requests` / `_check_approve_push_requests` / `_check_code_review_requests` / `_check_scheduling_kick_requests`）MUST NOT 因启动期恢复而停摆。

启动期全量扫描（`full_scan`）SHALL 拆分为「基线快照」与「扫描主体」两段：基线快照（`_update_known_state`）MUST 在 `event_bus.start()` 之后、任何后台扫描之前**同步**完成；扫描主体 MUST 异步执行，MUST NOT 占用启动线程至扫描结束。

#### Scenario: 启动时派发不阻塞 watcher 启动

- **WHEN** daemon 启动时存在可派发的 SPEC（drafted/ready/reviewing）且派发了实现或评审 Agent
- **THEN** `full_scan` 派发后立即返回，`event_bus.start()` 正常启动 watcher 与 periodic scanner 线程（进程线程数 ≥3），后续 STATE.md 变更持续产生事件

#### Scenario: 启动期恢复不阻塞主循环

- **WHEN** daemon 启动，且全量扫描的恢复分支派发了一个分钟级的 spec-review run
- **THEN** 主循环 SHALL 在数秒内打印 `Entering main loop` 并进入 tick，MUST NOT 等待该评审 run 收工

#### Scenario: 启动期文件信号消费者可用

- **WHEN** 主循环已进入 tick，用户经 Dashboard 写入任一文件信号（如 `code_review_request.json`）
- **THEN** 该信号 SHALL 在 ≤2 秒内被对应消费者拾取并处理，MUST NOT 因启动期恢复占线而滞留

#### Scenario: 运行期事件处理不被 Agent 阻塞

- **WHEN** watcher 检测到 STATE.md 变更并派发新的 Agent（含评审），同时已有 Agent 在运行
- **THEN** watcher 线程派发后立即返回，可继续检测后续变更，不被运行中的 Agent 阻塞

#### Scenario: 基线快照仍先于 watcher 扫描

- **WHEN** daemon 启动执行首扫
- **THEN** `_known_specs` 基线快照 SHALL 在任何 `_dispatch_changes` 扫描之前建立完成，存量 SPEC MUST NOT 被判为「新出现」而重放 hook 事件

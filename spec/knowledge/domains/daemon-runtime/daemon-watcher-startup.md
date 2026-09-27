<!-- knowledge: capability=daemon-watcher-startup rev=2 sources=spec/archive/2026-09-02-fix-worktree-spec-seeding,spec/archive/2026-09-24-fix-spec-review-blocking-dispatch -->

# Agent 派发异步化与 watcher 启动

PMEngine 的 Agent 派发全部走独立 worker 线程；daemon 启动序列保证 watcher 与主循环不被启动期恢复阻塞。

## 现行规则

- Agent 派发（`_process_queue` 与 `handle_event` 调用链）一律异步执行：每次运行在独立 worker 线程中启动，派发调用在启动线程后立即返回，不阻塞调用线程（含 daemon 启动时的初始 `full_scan`、EventBus watcher 事件处理、periodic scan）。
- 异步约束覆盖全部 agent 类型——implementer、fast-track、verifier、repair、spec-review 一视同仁，不存在「某一类 agent 在调用栈上同步执行」的例外。
- `FenixDaemon.start()` 即使在初始扫描派发了实现或评审 Agent，仍继续执行 `event_bus.start()` 并进入主循环；主循环内的文件信号消费者（admin invoke / cancel / approve push / code review / scheduling kick）不因启动期恢复停摆——启动期恢复派发分钟级 run 时，主循环须在数秒内进入 tick，文件信号须在 ≤2 秒内被对应消费者拾取。
- 启动期全量扫描拆两段：基线快照（`_update_known_state`）在 `event_bus.start()` 之后、任何后台扫描之前同步完成；扫描主体异步执行，不占用启动线程至扫描结束。存量 SPEC 不因基线缺失被判「新出现」而重放 hook 事件。
- Agent 运行以 `agents.max_concurrent` 为并发上限并行执行，完成一个自动补位下一个，任意时刻运行数不超上限；并发计数（`_active_runs`）与运行队列（`_run_queue`）的读写由锁保护，不超发。
- 共享可变状态线程安全：同一 SPEC 的重复调度由既有防重入守卫（`_handling_events`/`_spec_locks`）保证；STATE.md 写入继续由 `StateMachine.write_all` 的文件锁保护——并发不引入状态推进的重复或丢失。

## 溯源

- 2026-09-02 fix-worktree-spec-seeding — Agent 派发改异步 worker 线程：启动初扫与运行期事件处理不被 Agent 阻塞，多 Agent 按 `max_concurrent` 并发执行，共享状态加锁
- 2026-09-24 fix-spec-review-blocking-dispatch — 异步约束扩展到全部 agent 类型；初扫拆「基线快照同步 + 扫描主体异步」，主循环与文件信号消费者不再被启动期恢复阻塞

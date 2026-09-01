# fix-admin-run-blocks-mainloop

## Why

Administrator 处置在 daemon 主循环里同步执行（`_check_admin_invoke_requests` → `invoke_manual` → `run_administrator`，内部 `_run_claude` 阻塞直至处置完成），导致处置期间（实测数分钟）整个主循环停摆：其它 SPEC 的派发、admin_monitor 巡检、`.fenix/admin_invoke_request.json` 拾取全部延迟。实测 Dashboard 发起呼叫后的拾取延迟最高 231 秒（队列中前一个处置未结束时请求只能干等，且用户无从知晓原因）。

## What Changes

- **admin run 移出主循环**：`_check_admin_invoke_requests` 拾取到请求后改为投递到后台执行（线程），主循环保持 1s 粒度继续调度 SPEC 派发与 admin_monitor 巡检，不再被处置阻塞。
- **后台执行串行化**：Administrator 对主树独占资源（git 操作、进程管理、`.fenix/admin_disposition.json`、STATE.md）的处理必须互斥——同一时间最多一个 admin run 在执行，后续请求按到达顺序排队处理（不做并行多实例）。
- **落痕语义不变**：pending disposition（唤起前落）→ final disposition（结束后落）→ admin_monitor 升级告警的现有链路与记录格式保持不变；`invoke_manual` 的异常落痕（failed disposition）语义保留。
- **拾取及时性**：主循环不再阻塞后，invoke 请求应在拾取后一个扫描周期（约 1s）内被投递到后台队列；排队中的请求依序执行。
- Dashboard 侧"呼叫 Admin 介入"弹窗的排队提示已就绪（2026-09-01 已实现），无需随本 change 改动。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `administrator-agent`：执行模型从"主循环内同步执行"改为"后台串行队列异步执行"；主循环仅负责拾取请求与投递，处置落痕（pending/final disposition、升级告警）与结果语义保持不变。

## Impact

- `fenixd.py`：`_check_admin_invoke_requests`（拾取后投递，不再同步执行）
- `core/admin_monitor.py`：`invoke_manual` / `_invoke_administrator`（在后台线程上下文中执行，线程安全审视：AdminStore 追加、日志）
- `core/agent_runner/runner.py`：`run_administrator`（无接口变化；确认无主循环共享可变状态的并发访问）
- 并发安全：admin run 与主循环其余部分（state_machine 派发、admin_monitor 自动巡检）在主树上的并发访问需要互斥审视（admin run 期间主循环的 SPEC 派发可能修改 STATE.md/主树）
- Dashboard 弹窗无接口变化

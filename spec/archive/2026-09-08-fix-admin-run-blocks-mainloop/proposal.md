# fix-admin-run-blocks-mainloop

## Why

Administrator 处置在 daemon 主循环里同步执行（`_check_admin_invoke_requests` → `invoke_manual` → `run_administrator`，内部 `_run_claude` 阻塞直至处置完成），导致处置期间（实测数分钟）整个主循环停摆：其它 SPEC 的派发、admin_monitor 巡检、`.fenix/admin_invoke_request.json` 拾取全部延迟。实测 Dashboard 发起呼叫后的拾取延迟最高 231 秒（队列中前一个处置未结束时请求只能干等，且用户无从知晓原因）。

## What Changes

- **admin run 移出主循环**：`_check_admin_invoke_requests` 拾取到请求后投递到后台 worker 池，主循环保持 1s 粒度继续调度 SPEC 派发与 admin_monitor 巡检，不再被处置阻塞。
- **Administrator 支持并行多实例**：多个 worker 可同时执行多个 admin run（用户决策：不建 worktree、仍在主树操作，主树写冲突风险已评估并容忍）；worker 数量可配置（默认 2）。
- **处置状态文件按实例分离**：`.fenix/admin_disposition.json` 改为 `.fenix/admin_disposition-<run_id>.json`——每个实例 clear/write/read 自己的文件，提示词中指示 Admin 写入的路径按 run 注入，实例间不再互相覆盖。
- **落痕语义不变**：pending disposition（唤起前落）→ final disposition（结束后落，按 run_id 关联）→ admin_monitor 升级告警的现有链路与记录格式保持不变；`invoke_manual` 的异常落痕（failed disposition）语义保留；admin_alerts.json 仍是唯一聚合出口（watcher 监听点不变）。
- Dashboard 侧"呼叫 Admin 介入"弹窗的排队/实时输出已就绪（2026-09-01 已实现），无需随本 change 改动。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `administrator-agent`：执行模型从"主循环内同步执行、全局单一 disposition 文件"改为"worker 池并行执行、disposition 状态文件按 run 实例分离"；处置落痕（pending/final disposition、升级告警）与结果语义保持不变。

## Impact

- `fenixd.py`：`_check_admin_invoke_requests`（拾取后投递 worker 池，不再同步执行）
- `core/admin_monitor.py`：`invoke_manual` / `_invoke_administrator`（worker 线程上下文执行；AdminStore 按 run_id 关联已支持并行）
- `core/agent_runner/runner.py`：`run_administrator` / `_clear_admin_disposition` / `_read_admin_disposition`（disposition 路径按 run_id 参数化）
- `core/agent_runner/prompt_builder.py`：administrator 提示词中 disposition 写入路径按 run 注入
- 并发安全：多 worker 并发访问 AdminStore（文件锁）、agent_runner 共享状态审视
- Dashboard 弹窗无接口变化

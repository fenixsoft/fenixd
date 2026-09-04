# Proposal: add-run-cancel

## Why

当前框架没有任何单 run 粒度的终止手段：管理员要停止一个运行中的 runner，只能整体重启 daemon（`wait_for_running_agents` 全员 SIGTERM），误伤所有在跑 run。run 一旦启动，重试链会自动续 attempt、dispatch worker 会自动重派，管理员无法在发现 runner 行为异常（空转烧 token、跑错方向）时安全地掐掉它。

## What Changes

- 新增 `AgentRunner.cancel_run(run_id, reason, by)` 外部专用终止原语：登记取消旗标（基础 run_id 归一化，剥 `-a<n>` attempt 后缀），由持有 run 的线程在 `_run_claude` 轮询环内完成 terminate/kill 与终态落盘，不在调用线程做跨线程 kill。
- run jsonl 新增 `{"type": "cancelled"}` 终态行，与既有 `interrupted`（daemon 关停）/`error`（超时失败）三分。
- `AgentRunResult` 新增 `cancelled` 字段；`_execute_agent` 捕获专用异常 `RunCancelledError`：不重试、不计秒挂、不触发 provider 切换；attempt 循环顶部检查旗标，被取消的 run 不再派发后续 attempt。
- dispatch worker（implementer/fast-track/verifier/repair）对 `cancelled=True` 的结果走 hold-state 分支：只写 error 字段，不翻转 status、不动 `_retry_count`、不入队重派。
- 跨进程入口沿用 admin_invoke 文件信号模式：dashboard 原子写 `.fenix/cancel_run_request.json`，daemon 主循环消费后调用 `cancel_run`。
- Dashboard 新增 `POST /api/run-cancel` 接口与 runs 列表「终止」按钮（确认弹窗）；取消动作落 minor 级 admin_alerts 审计记录。

## Capabilities

### New Capabilities

- `run-cancel`: run 粒度的人工终止原语——外部专用 `cancel_run` 方法、取消旗标与 attempt 链终止、`cancelled` 终态行与结果标记、dispatch hold-state 处置、文件信号跨进程入口、dashboard API 与终止按钮、审计留痕。

### Modified Capabilities

<!-- 无：既有能力的 Requirement 不变更，本能力为纯新增 -->

## Impact

- `core/agent_runner/runner.py`：核心改动（取消旗标、`cancel_run`、`RunCancelledError`、轮询环检查、attempt 循环检查、`AgentRunResult.cancelled`）
- `core/pm_engine/dispatch.py`：`_run_agent_worker` / verifier 流水线 / repair worker 的 hold-state 分支
- `fenixd.py`：主循环新增 `_check_cancel_requests()` 文件信号消费
- `core/dashboard/data.py` + `core/dashboard/server.py`：`request_run_cancel` 信号写入 + `POST /api/run-cancel`
- `core/dashboard/static/src`：runs 列表终止按钮 + 确认弹窗；dist 产物需重建提交
- 测试：runner 取消路径、attempt 间隙、hold-state、文件信号全链路、not_running 返回

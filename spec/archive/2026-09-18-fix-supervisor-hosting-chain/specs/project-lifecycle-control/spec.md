## MODIFIED Requirements

### Requirement: 概览页启动项目 daemon

跨项目概览视图的项目卡片 MUST 提供「启动」操作，点击后通过 Dashboard 服务端启动该项目 fenixd daemon。服务端 MUST 复用该项目唯一 tmux session（`fenix_session.session_name(root)`，形如 `fenixd-<目录名>-<哈希6位>`），并在该 session 内拉起 **supervisor 托管入口**（`cd <root> && python3 .fenix/bin/fenixd_supervisor.py --project-root <root> >> .fenix/logs/supervisor.log 2>&1`，与 `fenix-setup` 一致）——tmux 仅作为脱离终端的承载手段，daemon MUST 由 supervisor 拉起。启动操作 MUST 幂等：项目 daemon 已在运行时重复点击 MUST 返回成功且不重复拉起。启动前 MUST 校验项目根存在 `.fenix` 框架软链接与 `STATE.md`，缺失时 MUST 返回可读错误且不产生 daemon 进程。启动成功后概览 MUST 在既有自动刷新周期内将该项目卡片更新为「运行中」。

#### Scenario: 启动未运行的 daemon
- **WHEN** 某项目 daemon 未运行，用户在概览卡片点击「启动」
- **THEN** 服务端创建该项目唯一 tmux session 并拉起 supervisor，由 supervisor 启动 fenixd，接口返回成功，卡片更新为「运行中」

#### Scenario: 启动后项目处于托管态
- **WHEN** 某 `stopped` 项目经概览卡片启动成功
- **THEN** 该项目的 `hosting` 字段为 `"managed"`（daemon 的父进程为该项目 supervisor），而非 `"unmanaged"`

#### Scenario: 重复启动已运行项目不重复拉起
- **WHEN** 项目 daemon 已在运行，用户再次点击「启动」
- **THEN** 接口返回成功并标记已运行，不创建第二个 session，项目仍只有一个 daemon 进程

#### Scenario: 非有效项目启动报错不产生进程
- **WHEN** 项目根缺少 `.fenix` 软链接或 `STATE.md`
- **THEN** 接口返回 400 与可读错误信息，且不产生任何 daemon 进程

### Requirement: 概览页停止项目 daemon

跨项目概览视图的项目卡片 MUST 提供「停止」操作，点击后服务端停止该项目 fenixd daemon（包含其 supervisor 托管进程）。停止 MUST 按序：写 `.fenix/stop` → 向该项目 daemon 进程发送 SIGTERM 触发既有优雅关闭 → 轮询等待 daemon 与 supervisor 双双退出至多约 30 秒 → 超时以 `tmux kill-session -t <session>` 强制终止并对残留进程补发 SIGKILL → 无论成败清除 `.fenix/stop`。停止 MUST NOT 只杀 daemon 而遗留 supervisor 空转，也 MUST NOT 只杀 supervisor 而遗留孤儿 daemon。停止操作 MUST 幂等：daemon 未运行时不报错。停止成功后概览 MUST 在既有自动刷新周期内将该项目卡片更新为「未运行」。

#### Scenario: 停止运行中的 daemon 优雅关闭
- **WHEN** 项目 daemon 在运行，用户在概览卡片点击「停止」
- **THEN** `.fenix/stop` 被写入后 daemon 收到 SIGTERM 优雅关闭并退出，supervisor 随之退出，接口返回成功，卡片更新为「未运行」

#### Scenario: 停止不残留 supervisor 或孤儿 daemon
- **WHEN** 某 `managed` 项目停止成功
- **THEN** 该项目根的 daemon 进程与 supervisor 进程均不存在，托管态为 `"stopped"`

#### Scenario: 优雅关闭超时强制终止
- **WHEN** daemon 收到 SIGTERM 后 30 秒内未退出
- **THEN** 服务端 `tmux kill-session` 强制终止并对残留进程补发 SIGKILL，接口仍返回成功

#### Scenario: 停止未运行的 daemon 幂等成功
- **WHEN** 项目 daemon 未运行，用户点击「停止」
- **THEN** 接口返回成功，不产生错误，不写入 `.fenix/stop`，卡片保持「未运行」

### Requirement: 管理 API 端点

Dashboard 服务端 MUST 提供五个项目管理端点：`POST /api/projects/<name>/start`（启动 daemon）、`POST /api/projects/<name>/stop`（停止 daemon）、`POST /api/projects/<name>/restart`（写 `.fenix/restart_request` 走 supervisor 优雅重启）、`POST /api/projects/<name>/install-hosting`（把 `unmanaged` 项目转入 supervisor 托管）、`DELETE /api/projects/<name>`（软删除）。端点 MUST 按项目名解析到当前发现结果中的路径；项目不存在或目录不存在（`exists=False`）时 MUST 返回 400 与错误信息。成功时 MUST 返回 JSON（含 `ok`、可选的 `session`/`error` 字段），并通过 SSE Hub 广播 `refresh` 事件使概览在自动刷新周期内跟随更新。所有操作因环境异常（tmux 不可用等）MUST 返回错误对象而不使请求 500。

#### Scenario: start/stop/restart/install-hosting/delete 端点正常返回
- **WHEN** 对监控中的项目依次调用 start、stop、restart、install-hosting、delete 五个端点
- **THEN** 五者均返回 `{"ok": true}` 及相应信息，且每个成功操作后概览收到 refresh 广播

#### Scenario: 对无 supervisor 项目调用 restart 返回可读错误
- **WHEN** 对 `unmanaged` 项目调用 restart 端点
- **THEN** 返回 `{"ok": false, "error": <含「未受 supervisor 托管」的可读信息>}`，且该请求 MUST NOT 被当作成功重启

#### Scenario: 未知项目返回 400
- **WHEN** 对不在监控列表的项目名调用任一管理端点
- **THEN** 接口返回 400 与「项目不存在」错误

#### Scenario: tmux 异常返回错误不 500
- **WHEN** 环境无法执行 tmux 命令（不可用/超时）
- **THEN** 接口返回带 `ok:false` 与错误信息的 JSON，HTTP 状态非 500

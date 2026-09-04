## ADDED Requirements

### Requirement: 概览页启动项目 daemon

跨项目概览视图的项目卡片 MUST 提供「启动」操作，点击后通过 Dashboard 服务端启动该项目 fenixd daemon。服务端 MUST 复用该项目唯一 tmux session（`fenix_session.session_name(root)`，形如 `fenixd-<目录名>-<哈希6位>`），以与 `fenix-setup` 一致的命令（`cd <root> && python3 .fenix/fenixd.py 2>&1 | tee .fenix/logs/stdout.log`）拉起。启动操作 MUST 幂等：项目 daemon 已在运行时重复点击 MUST 返回成功且不重复拉起。启动前 MUST 校验项目根存在 `.fenix` 框架软链接与 `STATE.md`，缺失时 MUST 返回可读错误且不产生 daemon 进程。启动成功后概览 MUST 在既有自动刷新周期内将该项目卡片更新为「运行中」。

#### Scenario: 启动未运行的 daemon
- **WHEN** 某项目 daemon 未运行，用户在概览卡片点击「启动」
- **THEN** 服务端创建该项目唯一 tmux session 并启动 fenixd，接口返回成功，卡片更新为「运行中」

#### Scenario: 重复启动已运行项目不重复拉起
- **WHEN** 项目 daemon 已在运行，用户再次点击「启动」
- **THEN** 接口返回成功并标记已运行，不创建第二个 session，项目仍只有一个 daemon 进程

#### Scenario: 非有效项目启动报错不产生进程
- **WHEN** 项目根缺少 `.fenix` 软链接或 `STATE.md`
- **THEN** 接口返回 400 与可读错误信息，且不产生任何 daemon 进程

### Requirement: 概览页停止项目 daemon

跨项目概览视图的项目卡片 MUST 提供「停止」操作，点击后服务端停止该项目 fenixd daemon。停止 MUST 先向该 tmux session 发送 SIGINT（`tmux send-keys -t <session> C-c`）触发 daemon 优雅关闭（执行已注册的 shutdown 清理），并轮询等待退出至多约 5 秒；超时仍未退出 MUST 以 `tmux kill-session -t <session>` 强制终止。停止操作 MUST 幂等：daemon 未运行时不报错。停止成功后概览 MUST 在既有自动刷新周期内将该项目卡片更新为「未运行」。

#### Scenario: 停止运行中的 daemon 优雅关闭
- **WHEN** 项目 daemon 在运行，用户在概览卡片点击「停止」
- **THEN** 服务端向该 session 发送 SIGINT，daemon 执行优雅关闭后退出，接口返回成功，卡片更新为「未运行」

#### Scenario: 优雅关闭超时强制终止
- **WHEN** daemon 收到 SIGINT 后 5 秒内未退出
- **THEN** 服务端 `tmux kill-session` 强制终止，接口仍返回成功

#### Scenario: 停止未运行的 daemon 幂等成功
- **WHEN** 项目 daemon 未运行，用户点击「停止」
- **THEN** 接口返回成功，不产生错误，卡片保持「未运行」

### Requirement: 软删除项目并写入忽略列表

跨项目概览视图 MUST 提供「删除项目」操作，语义为软删除：点击后 MUST 先停止该项目 daemon，再将该项目规范化路径写入 `~/.config/fenixd/dashboard.yaml` 新增的顶层 `ignored` 列表，随后该项目（无论此前是显式注册还是自动发现）MUST 不再出现在监控列表与自动发现结果中，直至用户手工从 `ignored` 移除该路径。软删除 MUST NOT 删除或修改项目目录中的任何文件与数据。删除操作 MUST 有二次确认（如确认对话框），确认文案 MUST 说明该操作保留项目文件、仅停止监控、可通过编辑配置文件恢复。

#### Scenario: 删除后不再被自动发现
- **WHEN** 用户对某自动发现项目执行删除并确认
- **THEN** 该项目 daemon 被停止，其路径被写入 `ignored`，之后的 `/api/projects` 与 `/api/overview` 均不再返回该项目，即使扫描目录中该目录仍存在 `STATE.md`

#### Scenario: 删除保留项目文件
- **WHEN** 用户删除某项目
- **THEN** 该项目目录、`STATE.md`、`openspec/`、`.fenix/` 等数据全部保留在磁盘，未被删除或改动

#### Scenario: 移除 ignored 条目后项目恢复
- **WHEN** 用户从 `dashboard.yaml` 的 `ignored` 中删除某项目路径
- **THEN** 该项目重新出现在自动发现/监控列表中（若目录仍为有效 Fenixd 项目）

### Requirement: 管理 API 端点

Dashboard 服务端 MUST 提供三个项目管理端点：`POST /api/projects/<name>/start`（启动 daemon）、`POST /api/projects/<name>/stop`（停止 daemon）、`DELETE /api/projects/<name>`（软删除）。端点 MUST 按项目名解析到当前发现结果中的路径；项目不存在或目录不存在（`exists=False`）时 MUST 返回 400 与错误信息。成功时 MUST 返回 JSON（含 `ok`、可选的 `session`/`error` 字段），并通过 SSE Hub 广播 `refresh` 事件使概览在自动刷新周期内跟随更新。所有操作因环境异常（tmux 不可用等）MUST 返回错误对象而不使请求 500。

#### Scenario: start/stop/delete 端点正常返回
- **WHEN** 对监控中的项目依次调用 start、stop、delete 三个端点
- **THEN** 三者均返回 `{"ok": true}` 及相应信息，且每个成功操作后概览收到 refresh 广播

#### Scenario: 未知项目返回 400
- **WHEN** 对不在监控列表的项目名调用任一管理端点
- **THEN** 接口返回 400 与「项目不存在」错误

#### Scenario: tmux 异常返回错误不 500
- **WHEN** 环境无法执行 tmux 命令（不可用/超时）
- **THEN** 接口返回带 `ok:false` 与错误信息的 JSON，HTTP 状态非 500

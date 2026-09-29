## ADDED Requirements

### Requirement: pushed 终态自动重启

任一 SPEC 状态迁移至 `pushed` 时，HookEngine 自动执行一次 `restart-dashboard` 动作（经内置默认 global hook 条目 `builtin-push-restart-dashboard`，无需用户配置）；dashboard tmux 会话以固化命令重启（`env -u CLAUDE_PID`），重启后以端口重新可服务为成功判据。该触发对全部 SPEC 生效，与既有用户级 hooks 配置叠加互不干扰。

#### Scenario: pushed 事件触发重启

- **WHEN** dashboard tmux 会话运行中，任一 SPEC 迁移至 pushed
- **THEN** dashboard 进程被重启（respawn），重启完成后端口可服务，且新进程加载主树最新代码

#### Scenario: 与用户 hooks 配置叠加

- **WHEN** 用户在 `hooks.specs` 为某 SPEC 配置了自定义 hook，同时该 SPEC 迁移至 pushed
- **THEN** 内置重启条目与用户自定义条目均被执行（互不吞并）

### Requirement: 去抖窗口

`restart-dashboard` 动作维护 60s 去抖窗口（进程内最近一次成功重启时间戳）：窗口内的后续触发幂等跳过（不执行 respawn），记 skipped 审计（与 disabled hook 审计同口味）；窗口外正常执行。重启失败不记录成功时间戳（下次触发可重试）。

#### Scenario: push 批次去抖

- **WHEN** 10s 内 3 个 SPEC 相继迁移至 pushed
- **THEN** 仅首次触发真实重启，后 2 次跳过并留 skipped 审计，dashboard 无多次闪断

#### Scenario: 失败可重试

- **WHEN** 首次触发重启失败（如 respawn 超时），60s 内再次出现 pushed 事件
- **THEN** 再次尝试重启（失败不占用去抖窗口）

### Requirement: 无会话静默跳过

dashboard tmux 会话不存在时（dashboard 未运行的环境），`restart-dashboard` 动作静默跳过：不执行 respawn、不记 failure 审计、不影响 SPEC 状态机与其它 hook 执行。

#### Scenario: dashboard 未运行不产噪音

- **WHEN** 无 dashboard tmux 会话的环境中有 SPEC 迁移至 pushed
- **THEN** 动作静默跳过，审计中无 failure 记录，无任何告警产生

### Requirement: 逃生键

配置键 `hooks.push_restart_dashboard`（bool，缺省 `true`）控制内置条目注入：`false` 时 `hook_config()` 不注入内置默认条目（pushed 不再触发重启），用户自定义 hooks 不受影响。设置页 HooksPanel 提供该开关的可视化控件，修改经既有配置写回链路持久化。

#### Scenario: 显式禁用

- **WHEN** 配置 `hooks.push_restart_dashboard: false` 后有 SPEC 迁移至 pushed
- **THEN** 无任何 dashboard 重启动作执行（内置条目未注入）

#### Scenario: 设置页开关生效

- **WHEN** 用户在设置页 HooksPanel 切换该开关
- **THEN** 配置写回 `.fenix/config.yaml`（经既有 /api/config 写链路），后续 pushed 事件按新值生效

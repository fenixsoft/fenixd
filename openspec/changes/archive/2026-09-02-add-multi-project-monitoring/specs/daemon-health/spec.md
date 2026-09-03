## ADDED Requirements

### Requirement: 每项目 daemon 运行健康检测

数据聚合层 MUST 为每个被监控项目提供 `daemon_health(project_root)` 函数，判定该项目 fenixd daemon 是否在运行，返回 `"running"` 或 `"stopped"`。判定规则 MUST 复用项目级唯一 tmux session（`fenixd-<目录名>-<路径哈希6位>`）的 `tmux has-session` 命中，且 MUST 兼容旧版固定 session `fenixd`（其 pane 当前工作目录解析后等于该项目根即视为运行）。任一命中即 `running`；`tmux` 不可用、subprocess 调用异常或均未命中 MUST 返回 `stopped`，且不抛异常。检测结果 MUST 带短 TTL 缓存（默认约 5s），避免高频轮询时重复 spawn 子进程。

#### Scenario: 运行中的项目判定为 running
- **WHEN** 项目的唯一 tmux session（`fenixd-<name>-<hash>`）存在
- **THEN** `daemon_health` 返回 `"running"`

#### Scenario: 旧版 session 兼容判定
- **WHEN** 项目无唯一 session，但存在旧版固定 session `fenixd` 且其 pane 工作目录等于项目根
- **THEN** `daemon_health` 返回 `"running"`

#### Scenario: 未运行/环境异常容错为 stopped
- **WHEN** 项目没有任何匹配的 tmux session，或 `tmux` 命令不可用/调用异常
- **THEN** `daemon_health` 返回 `"stopped"`，不抛异常

### Requirement: API 暴露 daemon 状态

`/api/projects` 与 `/api/overview` 返回的每个项目对象 MUST 包含 `daemon` 字段（`"running"`/`"stopped"`），由 `project_summary()`/`overview()` 基于 `daemon_health` 填充。任何项目在健康检测异常或数据源异常时，该字段 MUST 仍以 `"stopped"` 兜底返回，不使请求失败或返回 500。

#### Scenario: 概览与项目列表含 daemon 状态
- **WHEN** 监控列表包含一个运行中与一个未运行的项目，请求 `/api/overview` 或 `/api/projects`
- **THEN** 两个项目的 `daemon` 字段分别为 `"running"` 与 `"stopped"`

#### Scenario: 检测异常不 500
- **WHEN** 某项目的健康检测因环境异常无法判定
- **THEN** 该项目的 `daemon` 字段为 `"stopped"`，请求仍正常返回 200

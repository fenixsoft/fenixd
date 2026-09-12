## MODIFIED Requirements

### Requirement: 每项目 daemon 运行健康检测

数据聚合层 MUST 为每个被监控项目提供 `daemon_health(project_root)` 函数，判定该项目 fenixd daemon 是否在运行，返回 `"running"` 或 `"stopped"`。判定 MUST 复用 `core.fenix_session.is_running`：以 `/proc` 进程检测为**主判定**（匹配 `cwd` 等于该项目根、且 `cmdline` 含 `.fenix/fenixd.py` 或 `fenixd_supervisor` 的活跃进程，覆盖 supervisor 直启、tmux 内启动与**未经托管的裸 daemon**三种形态），仅在 `/proc` 不可用时回退项目级唯一 tmux session（`fenixd-<目录名>-<路径哈希6位>`）命中判定，且 MUST 兼容旧版固定 session `fenixd`（其 pane 当前工作目录解析后等于该项目根即视为运行）。任一命中即 `running`；`tmux` 不可用、subprocess 调用异常或均未命中 MUST 返回 `stopped`，且不抛异常。检测结果 MUST 带短 TTL 缓存（默认约 5s），避免高频轮询时重复 spawn 子进程。

数据聚合层 MUST 另提供 `hosting_state(project_root)`，返回 `"managed"`/`"unmanaged"`/`"stopped"`（语义见 `supervisor-hosting` 能力的「托管态判定」需求），用于把「进程在跑但无人托管」与「未运行」区分开。

#### Scenario: 运行中的项目判定为 running
- **WHEN** 项目根下存在活跃的 daemon 进程（无论其父进程是 supervisor、tmux 还是裸启动）
- **THEN** `daemon_health` 返回 `"running"`

#### Scenario: 裸 daemon 判定为 running 且托管态为 unmanaged（事故回归）
- **WHEN** 项目 daemon 在跑但无 supervisor 进程（如未经 `fenix-setup` 托管的存量项目）
- **THEN** `daemon_health` 返回 `"running"`，同时 `hosting_state` 返回 `"unmanaged"`

#### Scenario: 旧版 session 兼容判定
- **WHEN** `/proc` 不可读，项目无唯一 session，但存在旧版固定 session `fenixd` 且其 pane 工作目录等于项目根
- **THEN** `daemon_health` 返回 `"running"`

#### Scenario: 未运行/环境异常容错为 stopped
- **WHEN** 项目没有任何匹配的进程与 tmux session，或 `tmux` 命令不可用/调用异常
- **THEN** `daemon_health` 返回 `"stopped"`，不抛异常

### Requirement: API 暴露 daemon 状态

`/api/projects` 与 `/api/overview` 返回的每个项目对象 MUST 包含 `daemon` 字段（`"running"`/`"stopped"`），由 `project_summary()`/`overview()` 基于 `daemon_health` 填充；MUST 同时包含 `hosting` 字段（`"managed"`/`"unmanaged"`/`"stopped"`），基于 `hosting_state` 填充。任何项目在健康检测异常或数据源异常时，两个字段 MUST 仍以 `"stopped"` 兜底返回，不使请求失败或返回 500。

#### Scenario: 概览与项目列表含 daemon 与 hosting 状态
- **WHEN** 监控列表包含一个托管运行中、一个裸 daemon、一个未运行的项目，请求 `/api/overview` 或 `/api/projects`
- **THEN** 三个项目的 `daemon` 字段分别为 `"running"`/`"running"`/`"stopped"`，`hosting` 字段分别为 `"managed"`/`"unmanaged"`/`"stopped"`

#### Scenario: 检测异常不 500
- **WHEN** 某项目的健康检测因环境异常无法判定
- **THEN** 该项目的 `daemon` 与 `hosting` 字段均为 `"stopped"`，请求仍正常返回 200

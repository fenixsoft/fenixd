## Why

当前 fenixd、fenix-desktop 等项目的开发各自由独立 fenixd daemon 监控（每项目一个 STATE.md、独立进程，这是刻意隔离设计），但共享 Dashboard 的监控列表只包含**手动注册**的项目——现状注册表里只有 `fenixd`（以及一个 /tmp 残留的 test-project），导致用户打开 Dashboard 只能看到 fenixd 的信息，无法统一掌握所有被 fenixd 监控项目的开发状态。需要让 Dashboard 以自动发现为主、手动注册为辅，聚合展示所有项目的开发进度，并暴露每个项目 daemon 是否在运行的健康状态。

## What Changes

- **自动发现为主**：`Registry.discover()` 在 `scan_dirs` 未配置时，默认扫描用户主目录下的一级子目录，凡同时存在 `STATE.md` 与 `.fenix/config.yaml` 即识别为 Fenixd 项目并纳入监控列表（volatile，不落盘）。
- **手动注册为辅**：保留 `projects` 显式注册与 `--add-project`（含 `/fenix-dashboard` skill 的自动注册）；新增 `--remove-project <path>` 支持把已注册项目移出监控列表（用于清理残留项目如 `/tmp/test-project`）。
- **daemon 健康状态（新增）**：复用 `bin/fenix_session.py` 的项目级唯一 tmux session 判定（含旧版固定 `fenixd` session 兼容），为每个被监控项目检测其 fenixd daemon 是否运行，返回 `running`/`stopped`。
- **API 透传**：`/api/projects` 与 `/api/overview` 的每个项目对象新增 `daemon` 字段；检测异常时容错为 `stopped`，不使请求失败。
- **UI 展示**：Dashboard 概览视图的项目卡片展示 daemon 健康徽标（运行中/未运行），自动发现的项目仍带「自动」标记；多项目统一展示。
- 不改变每项目独立 daemon 的隔离架构；不初始化 trendradar2（该能力无关）。

## Capabilities

### New Capabilities
- `project-discovery`: 自动扫描为主、显式注册为辅的多项目发现；支持从监控列表移除项目
- `daemon-health`: 每项目 fenixd daemon 运行健康状态检测，经 API 暴露
- `dashboard-overview`: 概览视图统一展示多项目开发状态与 daemon 健康徽标

### Modified Capabilities
<!-- openspec/specs/ 为空，既有 add-fenix-dashboard 的能力仍在其 change 内；
     本变更以新增能力的形式承载对 dashboard-server / dashboard-ui 的增量要求。 -->

## Impact

- `core/dashboard/registry.py` — `discover()` 默认扫描逻辑、`remove_project()`、`discover()` 返回 `registered`/`discovered` 区分
- `core/dashboard/data.py` — `daemon_health()` 检测函数；`project_summary()`/`overview()` 增加 `daemon` 字段
- `core/dashboard/server.py` — `/api/projects`、`/api/overview` 透传 `daemon` 字段
- `bin/fenix_dashboard.py` — `--remove-project` 子命令；复用 fenix_session 的项目根/session 判定
- `core/dashboard/static/app.js` / `style.css` — 概览卡片 daemon 徽标渲染
- `tests/test_core.py` — 新增发现/健康检测/移除的单测

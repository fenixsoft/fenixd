## Why

2026-09-12 实锤事故：`/data`（`/dev/sda1`）硬件故障（`DID_BAD_TARGET`、superblock 写失败），`/root/Qwen3.5-0.8B-Instruct`（指向 `/data` 的符号链接）目标目录数据块不可读。默认扫描根 `~` 的一级子目录探测在 EIO 上抛出，`discover()` **整体**失败 → `/api/overview` 返回 500 → 概览整页「概览数据加载失败」。

一个扫描根下**外部、非 Fenixd 的**目录发生 I/O 故障，拖垮了整个多项目 Dashboard。同时暴露两条逃生通道都被堵死：`ignored` 软删除对不可读路径完全无效（过滤在探测之后，探测先抛异常），用户连「把它忽略掉」都做不到；项目发现缓存异常时不更新时间戳，导致每个请求重试重炸。

## What Changes

- **发现层容错**：`Registry.discover()` 逐子目录探测加异常隔离——任何 `OSError`（含 EIO）只跳过该子目录并写一条 WARNING 日志，MUST NOT 中断整体发现或显式项目列表。UI 对此静默（仅落日志）。
- **忽略列表前置**：`ignored` 过滤前移至目录可读性探测之前，使软删除对不可读路径同样生效（当前实现下忽略列表救不了坏目录）。
- **聚合层隔离**：`overview()` 与 `_api_projects()` 逐项目隔离——单项目异常降级为该项目摘要的 `error` 字段（复用 `data.py:3753` 既有 schema），其余项目与 `totals` 照常返回。
- **发现缓存语义**：`DashboardHTTPServer.projects()` 在 `discover()` 抛异常时保留上次成功结果并记录错误，MUST NOT 使每个请求都重试重炸。
- **前端降级展示**：概览页请求失败时 MUST 提供可操作的降级视图（错误提示 + 重试入口），而非空白页。
- 无破坏性变更，无配置迁移。

## Capabilities

### New Capabilities
<!-- 无新增能力：本次为既有能力的需求强化 -->

### Modified Capabilities
- `project-discovery`：扫描容错（单个不可读/异常子目录 MUST 不中断整体发现）+ `ignored` 过滤前置于探测之前（软删除对不可读路径同样生效）。
- `dashboard-server`：既有「解析失败的数据源 MUST 以容错方式跳过并以字段标记，不使整个请求失败」的适用范围扩展到**项目发现层**与**跨项目聚合层**；补充发现缓存的异常语义。
- `dashboard-overview`：概览在单项目异常时的降级展示契约（项目卡片携带 `error` 字段，其余项目与 totals 不受影响；前端不因单项目异常丢失整页）。

## Impact

**代码**
- `core/dashboard/registry.py`：`discover()` 子目录循环（约 129-141 行）——异常隔离 + `ignored` 前置。
- `core/dashboard/server.py`：`DashboardHTTPServer.projects()`（211-217 行）缓存异常语义；`_api_projects()`（355-372 行）逐项目隔离。
- `core/dashboard/data.py`：`overview()`（3737-3779 行）逐项目隔离与降级字段。
- `core/dashboard/static/src/pages/overview/index.tsx`：请求失败时的降级视图；需重建 `core/dashboard/static/dist/index.html`。

**既有能力交互**
- `project-lifecycle-control`（软删除/忽略列表）的 requirement 文本不变，但其「写入 `ignored` 后 MUST 不再出现在监控列表」的要求借本次改动才对**不可读路径**成立。为避免同一行为出现两份契约源（见 [[fenixd-verdict-retry-misattribution-incident]] 一类契约单一性教训），该行为统一由 `project-discovery` 的 delta 承载，不单列 delta。

**非目标**
- 不修 `/data` 的硬件故障（运维事项）。
- 不改变默认扫描根为 `~` 的既有语义，不引入「跳过符号链接」策略。
- 不引入 per-project 的 I/O 故障自动摘除/熔断机制（本次只做「不拖垮整体」）。

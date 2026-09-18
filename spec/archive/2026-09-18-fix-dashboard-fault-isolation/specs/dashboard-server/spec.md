## MODIFIED Requirements

### Requirement: 聚合数据 API

Dashboard 服务器 MUST 提供以下 REST JSON API（仅监听 127.0.0.1）：
- `GET /api/projects`：监控项目列表及各自聚合摘要；
- `GET /api/overview`：跨项目状态统计（各 status 的 SPEC 数）、任务总进度、问题/阻塞数、活跃运行数；
- `GET /api/specs?project=<name>`：某项目全部 SPEC 摘要（状态、优先级、错误、任务进度、验证进度、最新运行）；
- `GET /api/specs/<spec>?project=<name>`：单个 SPEC 完整详情（任务分组、验证进度、场景级测试结果、bug 列表、截图列表、运行记录）；
- `GET /api/runs/<run_id>?project=<name>`：单次运行的产物流（LLM 事件列表、终止状态）；
- `GET /api/events?project=<name>&minutes=N`：最近 N 分钟的结构化事件（来自 `.fenix/logs/fenixd*.log`）。
以上 API MUST 以 `application/json` 返回，解析失败的数据源（如损坏的 progress 文件）MUST 以容错方式跳过并以字段标记，不使整个请求失败。

容错范围 MUST 覆盖**项目发现层**与**跨项目聚合层**，不限于单个数据源文件：

- **发现层**：`GET /api/projects` 与 `GET /api/overview` 所依赖的 `Registry.discover()` 抛出异常时，MUST NOT 使请求返回 500；此时 MUST 回退到最近一次成功的发现结果（见「发现结果缓存的异常语义」），并在响应中以字段标记该情形。
- **聚合层**：`overview()` 与 `_api_projects()` 遍历项目列表时 MUST 对每个项目做异常隔离。单个项目的摘要计算或状态解析抛出任何异常时，MUST 只影响该项目：该项目摘要 MUST 携带 `error` 字段记录失败原因（复用既有摘要 schema 中的 `error` 键），MUST NOT 计入 `totals` 的任何计数，其余项目摘要与 `totals` MUST 照常返回，整个请求 MUST 仍返回 200。
- 单个项目失败 MUST NOT 使其它项目缺失、中断遍历顺序或改变其余项目的字段。

#### Scenario: 概览聚合统计正确
- **WHEN** 两个项目分别有多个处于不同状态的 SPEC
- **THEN** `/api/overview` 返回各 status 计数与任务进度按项目正确聚合

#### Scenario: 损坏数据源容错
- **WHEN** 某项目的 `.fenix/verify-progress/<spec>.json` 内容损坏或非对象
- **THEN** 相关 API 仍正常返回，该 SPEC 的验证进度字段标记为异常或空，不导致请求 500

#### Scenario: 单项目摘要异常降级为卡片 error 字段
- **WHEN** 某项目的 `.fenix/STATE.md` 存在性探测或解析抛出 `OSError`（errno `EIO`），其余项目正常
- **THEN** `/api/overview` 返回 200；该项目的摘要带非空 `error` 字段描述失败原因；其余项目摘要与 `totals` 与无该项目失败时一致

#### Scenario: 单项目异常不污染 totals
- **WHEN** 某项目在聚合时抛出异常
- **THEN** 该项目的 `spec_count`/`task_done`/`task_total`/`problems`/`active_runs` MUST NOT 被计入 `totals`

#### Scenario: 项目列表端点同样隔离
- **WHEN** 某项目在 `_api_projects()` 的逐项目摘要计算中抛出异常
- **THEN** `/api/projects` 返回 200，该项目带 `error` 字段，其余项目正常列出

#### Scenario: 发现层异常不使概览 500
- **WHEN** `Registry.discover()` 本身抛出异常（未预期的发现层故障）
- **THEN** `/api/overview` 与 `/api/projects` MUST 返回 200 并使用上一次成功的发现结果，MUST NOT 返回 `500 Internal Server Error`

## ADDED Requirements

### Requirement: 发现结果缓存的异常语义

`DashboardHTTPServer.projects()` MUST 在 `Registry.discover()` 抛出异常时**保留上一次成功结果**（若从未成功过则为空列表）并记录错误，MUST NOT 让异常冒泡到请求处理层。

缓存时间戳的更新 MUST NOT 受发现异常影响：异常发生后 MUST 照常更新缓存时间戳，使得 TTL（默认 10s）内的后续请求复用上次成功结果，而非每个请求都重新执行一次注定失败的发现。TTL 到期后 MUST 重新尝试发现，成功则替换缓存，失败则继续保留上次成功结果。

本要求是兜底防线：发现层已按 `project-discovery` 的容错要求逐子目录隔离，正常情况下不会抛异常；本要求覆盖任何未预期的发现层异常。

#### Scenario: 发现异常时复用上次成功结果
- **WHEN** 一次成功的发现已缓存，随后 `discover()` 抛出异常，紧接着发起 `/api/overview` 请求
- **THEN** 响应 200 且项目列表等于上次成功发现的结果

#### Scenario: 异常后 TTL 内不重复执行发现
- **WHEN** `discover()` 持续抛异常，在 TTL（10s）内向服务器发起多次请求
- **THEN** `discover()` 的调用次数 MUST 为 1（缓存时间戳照常推进），而非每请求一次

#### Scenario: TTL 到期后重试并可恢复
- **WHEN** `discover()` 先抛异常、TTL 到期后恢复正常返回值
- **THEN** TTL 到期后的首次请求触发重新发现并替换缓存，后续请求返回恢复正常后的项目列表

#### Scenario: 从未成功过时返回空列表而非报错
- **WHEN** 服务器启动后的首次 `discover()` 即抛出异常
- **THEN** `/api/projects` 与 `/api/overview` MUST 返回 200，项目列表为空数组，`totals` 为零值

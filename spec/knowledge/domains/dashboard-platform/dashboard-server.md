# Dashboard 服务端

<!-- knowledge: capability=dashboard-server rev=2
     sources=spec/archive/2026-09-02-add-fenix-dashboard,spec/archive/2026-09-18-fix-dashboard-fault-isolation -->

跨项目 Web 仪表盘的独立服务进程：多项目注册发现、聚合数据 API、截图等静态资源安全服务。

## 规则

- 独立进程与统一入口：`bin/fenix_dashboard.py` 为唯一入口，`--serve` 启动 Web 模式（缺省）、`--tui` 保留终端模式、`--add-project <path>` 注册项目、`--port` 覆盖端口；服务由数据聚合层（`core/dashboard/data/` 包）、注册发现（registry）与纯标准库 HTTP 服务组成。
- 端口：默认 8787，取值解析链为 `--port > dashboard.yaml port > config port > 8787`；服务仅绑定 127.0.0.1。端口占用时的接管/报错退出语义由 `dashboard-instance-lifecycle` 能力承载。
- 多项目注册与发现：监控配置在 `~/.config/fenixd/dashboard.yaml`，格式为 `port`、`projects: [{name, path}]`、`scan_dirs: [父目录]`；`discover()` 合并显式 `projects` 与 `scan_dirs` 扫描结果，显式 `projects` 始终出现在监控列表（即使扫描未命中）；`--add-project` 按路径去重（已存在跳过并提示）。扫描识别条件与发现层容错由 `project-discovery` 能力承载。
- 聚合数据 API（均以 `application/json` 返回，仅 127.0.0.1 可达）：`GET /api/projects`（项目列表及聚合摘要）、`GET /api/overview`（跨项目状态统计/任务总进度/问题数/活跃运行数）、`GET /api/specs?project=`（SPEC 摘要）、`GET /api/specs/<spec>?project=`（完整详情）、`GET /api/runs/<run_id>?project=`（运行产物流）、`GET /api/events?project=&minutes=N`（最近结构化事件）。
- 容错分三层，任何一层失败都不得使请求 500：
  - 数据源层：单个数据源（如损坏的 verify-progress 文件）解析失败 → 跳过并以字段标记；
  - 聚合层：`overview()` 与 `_api_projects()` 逐项目异常隔离，失败项目摘要携带 `error` 字段、不计入 `totals`，其余项目与 `totals` 照常返回 200；
  - 发现层：`discover()` 抛出异常 → 回退最近一次成功的发现结果并在响应字段标记。
- 发现结果缓存异常语义：`projects()` 在发现异常时保留上次成功结果（从未成功过则空列表）；缓存时间戳无条件推进——TTL（缺省 10s）内后续请求复用上次结果而非重试注定失败的发现，TTL 到期重新尝试，成功即替换缓存。
- 截图静态资源：`GET /screenshots/<project>/<spec>/<file>` 服务项目 `.fenix/verify-progress/<spec>/screenshots/` 下的 PNG（`image/png`）；路径必须经 `Path.resolve()` 校验后仍位于该项目 screenshots 目录内（防路径穿越），`project` 必须已注册，非法段返回 404/403。
- run 行读取须容错 UTF-8 解码异常，不因脏字节中断聚合。

## 溯源

- 史前复原 — dashboard 由数据层、多项目注册发现与 HTTP 服务组成，bin 统一入口启动；run 行读取须容错 UTF-8 解码异常
- 2026-09-02 2026-09-02-add-fenix-dashboard — 建立多项目注册发现、六端点聚合 API、截图路径穿越防护与独立进程端口管理
- 2026-09-18 2026-09-18-fix-dashboard-fault-isolation — 容错范围扩展至发现层与聚合层（逐项目隔离、error 字段、不污染 totals），并固化发现结果缓存的异常语义（保留上次成功结果、TTL 无条件推进）

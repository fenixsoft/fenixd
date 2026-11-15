# Dashboard 服务端

<!-- knowledge: capability=dashboard-server rev=4
     sources=spec/archive/2026-09-02-add-fenix-dashboard,spec/archive/2026-09-18-fix-dashboard-fault-isolation,spec/knowledge/_inbox/done/memory-distill-ops-runbook.md,spec/knowledge/_inbox/done/2026-11-15-dashboard-dist-index-missing-404.md -->

跨项目 Web 仪表盘的独立服务进程：多项目注册发现、聚合数据 API、前端静态入口与截图等静态资源安全服务。

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
- 前端静态入口单文件承载全站：静态路由以 `core/dashboard/static/dist/index.html` 为根入口，该文件缺失时 `/` 与所有页面路径统一返回 JSON `{"error": "Not Found"}` 404——进程与监听均正常（公网隧道透传同样 404），呈现「服务挂了」的外观。判别点在根路径：陈旧进程的签名是特定新端点 404 而 `/` 照常服务（见 `dashboard-instance-lifecycle`），入口产物缺失则连 `/` 本身也 404。
- dist 是 gitignored 构建产物，git 无法恢复；误删/丢失后的唯一恢复路径是重建：`cd core/dashboard/static && pnpm build`（约 1-2 分钟），重建完成全站即恢复，期间无需重启 dashboard 进程——静态文件按请求实时读盘（Python 读侧改动才须重启，口径见 `dashboard-instance-lifecycle` 双向验证铁律）。
- 不可达排查分层：进程/端口 → HTTP 状态码 → dist 产物完整性。响应头 `Server: BaseHTTP` + JSON 404 体说明服务端健康（进程、路由注册均活着），问题在静态入口产物而非服务——先查 `dist/index.html` 在不在，再考虑重启。
- run 行读取须容错 UTF-8 解码异常，不因脏字节中断聚合。
- 验证与取证操作纪律：禁止以 curl 请求破坏性 POST 端点做验证——clear-todo 等全局动作一经请求立即执行、无确认与撤销，曾真实清空多项目 todo.md；API 404 取证看响应体区分路由层（无 handler 注册）与 handler 层（handler 返回 not found）；探测一律用真实注册项目名——`__probe__` 类假项目必然 404，是假阳性不是证据。假项目 fixture 验证以 `HOME=/tmp/<临时目录>` 起独立实例最彻底（registry 与扫描根全指临时 HOME，预写 dashboard.yaml 注册 fixture、`scan_dirs: []`），不烧真实项目 token。

## 溯源

- 史前复原 — dashboard 由数据层、多项目注册发现与 HTTP 服务组成，bin 统一入口启动；run 行读取须容错 UTF-8 解码异常
- 2026-09-02 2026-09-02-add-fenix-dashboard（spec/archive/2026-09-02-add-fenix-dashboard） — 建立多项目注册发现、六端点聚合 API、截图路径穿越防护与独立进程端口管理
- 2026-09-18 2026-09-18-fix-dashboard-fault-isolation（spec/archive/2026-09-18-fix-dashboard-fault-isolation） — 容错范围扩展至发现层与聚合层（逐项目隔离、error 字段、不污染 totals），并固化发现结果缓存的异常语义（保留上次成功结果、TTL 无条件推进）
- 2026-11-04 memory-distill-ops-runbook（spec/knowledge/_inbox/done/memory-distill-ops-runbook.md） — 折叠验证取证纪律：禁 curl 破坏性 POST 端点、404 看响应体分层取证、探测用真实项目名、HOME=/tmp fixture 实例配方
- 2026-11-15 2026-11-15-dashboard-dist-index-missing-404（spec/knowledge/_inbox/done/2026-11-15-dashboard-dist-index-missing-404.md） — 折叠静态入口产物完整性规则：dist/index.html 为静态路由根入口、缺失即全站 JSON 404（进程健在的「假挂」外观与根路径判别点）、gitignored 产物唯一恢复路径 `pnpm build` 重建免重启、不可达排查三层分层

# Add Dashboard Incremental Data

## Why

实测（150 spec 现状，Playwright + cProfile）Dashboard 存在三套全量重算环叠加：

1. **前端 2s 固定轮询**：`/api/overview`、`/api/specs`、`/api/alerts` 全部每 2 秒一次；spec 列表页 3 秒内实测 10 次 `/api/specs` 请求。
2. **watcher 全量重组**：`watcher.py` 日志一有追加（daemon 活跃时几乎每秒）就重组 overview + 全量 spec_summary + 变更 spec_detail 广播（100KB+/次）。
3. **服务端每请求 O(N) 无记忆**：`parse_state` 每次全量解析 STATE.md（56KB→10000 spec 时 5MB）；`project_summary` 每次重复 YAML 配置解析（实测占单次 62% 时间）+ `cleanup_runs`（27ms）；每个 `spec_summary` 6 次独立磁盘 IO（get_runs/count_scenarios/parse_tasks/read_spec_mode…）。

推演：10000 spec 时 `/api/specs` 单次计算约 4 秒（当前 44ms × 92 倍），每 2s 轮询一次 → 架构性失效；watcher 每秒 7 万次文件 stat；日志全量扫描 700MB。

线 A（gzip 压缩 + 缓存头 + 紧凑 JSON）已单独落地（传输 3.1MB→1.0MB），本 SPEC 解决**计算与广播**侧的规模瓶颈：把热路径从「O(N) 每请求全量重算」改为「启动一次性构建 + O(变更) 增量」，并给 10000 spec 留出分页与监视优化基础。

## What Changes

1. **内存摘要索引**：server 侧新增 `{project → {spec_name → summary}}` 摘要缓存。启动/首次请求构建一次；以 `(path, mtime_ns, size)` 为失效键（与 `_RUN_TASK_CACHE` 同模式，均有界）；watcher 检测到某 spec 文件变更只重算该 spec 一条。`/api/specs` 与 SSE 广播改读索引，不再每次全量重算。
2. **watcher 增量广播**：`_handle_state_change` 改为推 diff——只带变更 spec 的摘要（`{spec, summary}` 单条）与变化后的统计合并量；不再每次推全量 specs+details+overview。广播 payload 由 100KB/次 降至 ~1KB/次。
3. **前端双通道去重**：v3 SPA 改为 SSE 事件驱动刷新；2s 固定轮询降为 30~60s 兜底心跳 + `visibilitychange` 时补刷；spec 表格接收增量事件 patch 单行（含新增/删除/排序）。轮询与 SSE 不再叠加。
4. **配置解析缓存**：`read_effective_config` / `read_spec_mode` 按 `(path, mtime, size)` 缓存（实测可杀掉 project_summary 62% 时间）；`cleanup_runs` 节流到 ≥60s 一次。
5. **日志尾部索引**：为 `.fenix/logs/fenixd*.log` 维护行偏移索引（`.fenix/logs/.idx/`），`get_spec_timeline` / `get_recent_events` 只读尾部 1MB 窗口内的偏移段，替代全量 7.5MB（10000 spec 时 700MB）扫描。
6. **watcher 目录级签名跳层**：保 D2 零新增依赖（不引入 watchdog）。改为两级签名：顶层数据源目录（STATE.md/spec/changes/.fenix/...）mtime 未变则跳过整棵子树；spec 目录 mtime 未变则跳过该 spec 的 7 个文件 stat。10000 spec 时每轮 stat 从 7 万次降至 O(目录数)（约 1 万次目录级 stat，页缓存内 ≈10ms）。
7. **连接上限**：SSE 连接数上限 32（超限拒绝新连接，客户端退化为轮询）；`ThreadingHTTPServer` 线程数上限 64（超限 503，防标签页风暴耗尽资源）。

## Capabilities

### New Capabilities
- `dashboard-spec-summary-index`: 内存摘要索引与配置解析缓存；/api/specs 与广播改读索引，变更只重算单条
- `dashboard-incremental-watcher`: watcher 增量广播（diff）+ 目录级签名跳层监视
- `dashboard-sse-refresh`: 前端 SSE 驱动刷新：心跳降频、visibilitychange 补刷、spec 表格单行 patch
- `dashboard-log-offset-index`: fenixd 日志行偏移索引，时间轴/事件查询只读尾部窗口
- `dashboard-connection-limit`: SSE 与 HTTP 线程连接上限

### Modified Capabilities
<!-- 无既有 spec/specs/ 能力要求变更（前端轮询语义属实现层，不改变对外 API 契约） -->

## Impact

- **代码**：`core/dashboard/data.py`（索引/缓存/日志索引）、`core/dashboard/watcher.py`（增量+签名跳层）、`core/dashboard/server.py`（连接上限/索引接线）、`core/dashboard/static/v3/src/`（前端去重）
- **构建产物**：`core/dashboard/static/v3/dist/` 需重建并提交（验证链路依赖主树 dist 实时读盘）
- **API 契约**：`/api/specs`、`/api/overview`、`/api/stream` 响应结构不变（增量仅影响 SSE `state` 事件的 details 形态，旧客户端按全量兼容降级）
- **依赖**：无新增（D2 保持）
- **性能目标**：150 spec 下 `/api/specs` 轮询路径 CPU 降 ~95%；10000 spec 时 `/api/specs` 有界在 <300ms（索引读 + 分页）
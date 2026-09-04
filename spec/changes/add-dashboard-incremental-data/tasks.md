# Tasks

## Deliverables

```yaml
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/watcher.py
  kind: modify
- path: core/dashboard/static/v3/src/
  kind: modify
- path: core/dashboard/static/v3/dist/
  kind: modify
- path: tests/test_dashboard_index.py
  kind: new
- path: tests/test_dashboard_watcher_incremental.py
  kind: new
```

## 1. spec 摘要索引与配置缓存（dashboard-spec-summary-index）

- [x] 1.1 data.py 新增 `SummaryIndex` 类：持每项目 `{spec_name: {"summary": dict, "sigs": {path: (mtime_ns, size)}}}`；依赖文件集合枚举函数 `_spec_dep_files(proot, spec_name)` 必须对齐 spec_summary 实际读路径（tasks.md / specs/ 目录整体 / .openspec.yaml / .fenix/runs/ 目录 / verify-progress 相关文件），单向全覆盖（宁多勿漏，将 specs/ 目录整体入签名）
- [x] 1.2 `SummaryIndex.get(proot, specs) -> list[spec_summary]`：签名未变直返缓存；变化只重算该 spec；STATE.md 签名变化触发该项目全量重建（调用方传入 STATE.md 签名）
- [x] 1.3 server.py 在 DashboardHTTPServer 上挂 `self.summary_index`（线程安全：Lock 保护，读多写少）；`_api_specs` 改走 `summary_index.get`
- [x] 1.4 data.py `read_effective_config` / `read_spec_mode` 加签名缓存：`key=(真实路径, mtime_ns, size)`，命中直接返回；写路径不维护显式失效（mtime 自然失效，与 _RUN_TASK_CACHE 同模式）
- [x] 1.5 data.py `cleanup_runs` 加项目级节流：`(proot, last_run_ts)` 记录，≥60s 才实际执行；节流期直接返回 0
- [x] 1.6 测试：tests/test_dashboard_index.py——命中零读取、单变更只重算一条、STATE.md 变更全量重建、配置缓存命中/写回失效、cleanup 节流（mock 计时或文件操作计数）

## 2. watcher 增量广播与目录签名跳层（dashboard-incremental-watcher）

- [x] 2.1 watcher.py 两级签名枚举：重写 `_iter_project_files` 为 `_iter_project_sigs(proot)`——顶层数据源集合（STATE.md、openspec/changes、.fenix/logs、.fenix/runs、.fenix/verify-progress、.fenix/admin_alerts.json）目录签名 `(mtime_ns, size, ctime_ns)`；签名未变跳过整棵子树
- [x] 2.2 spec 目录级跳层：仅对签名变化的 spec 目录做文件级签名比对（用 1.1 的依赖文件集合）；清理已删除 spec 的签名条目
- [x] 2.3 `_handle_state_change` 改增量广播：`{type:"state", project, specs:[{spec, summary|null}...], details:{变化 spec 详情}}`，不下发 overview；spec_summary 读取改走 SummaryIndex（1.2）
- [x] 2.4 新 spec 创建（changes/ 目录级签名变化）→ 广播该 spec `{spec, summary:null}` 前的正常摘要条目 + 详情（详情以 spec_detail 计算）
- [x] 2.5 测试：tests/test_dashboard_watcher_incremental.py——日志追加推 <2KB 增量、单 spec 变更推单条、spec 删除推 null 标记、目录未变零文件级 stat、规模基准（构造 1000 假 spec 目录单轮 <50ms）

## 3. 前端 SSE 增量驱动（dashboard-sse-refresh）

- [x] 3.1 v3 前端 spec 数据流改造：本地 `Map<spec, summary>` 摘要表；首屏 `/api/specs` 全量建立；`state` 增量事件入 patch 队列（同 spec 1s 去重合并）；表格由本地表渲染
- [x] 3.2 表格删除/新增处理：`summary:null` 移除行；新增 spec 插序；统计徽标从本地表推导
- [x] 3.3 轮询降频：overview / specs / alerts 轮询 2s → 30~60s 心跳 + `visibilitychange` 立即校准 + SSE 断线时心跳兜底；overview 仍作为 30s 校准源
- [x] 3.4 搜索/筛选输入防抖 ≥300ms 走本地表过滤；本地表空时才回退后端请求
- [x] 3.5 重建 dist 并提交（core/dashboard/static/v3/dist/；验证依赖主树 dist 实时读盘，重建后必须提交）
- [x] 3.6 测试：playwright 场景验证——生产构建下 SSE 增量 patch（行不重建断言）、删除事件移除行、overview 请求间隔 ≥30s、visibilitychange 补刷、断线降级兜底、输入防抖无后端请求

## 4. 日志块偏移索引（dashboard-log-offset-index）

- [x] 4.1 data.py 日志索引：`.fenix/logs/.idx/fenixd.log.offsets.json`（size + 每 64KB 块首行偏移）；重建/追加更新逻辑；损坏容错（缺失/不匹配 → 重建一次）
- [x] 4.2 `get_recent_events` 改索引读段：时间窗口定位块 → 只读对应块（≤1MB），结果与全量口径一致；超窗截断语义
- [x] 4.3 `get_spec_timeline` 改索引读段（同样尾部窗口策略，保持 Transition 提取逻辑不变）
- [x] 4.4 测试：大文件（≥1MB 构造）下 query 只读 ≤1MB 字节（read 计数断言）、追加后索引热更新（重建 0 次）、索引损坏重建容错、超窗截断返回不抛错

## 5. 连接上限（dashboard-connection-limit）

- [x] 5.1 server.py `MAX_SSE_CONNECTIONS=32`：SSEHub.register 计数，超限拒绝（503 + JSON 错误体）；断开 `unregister` 回落
- [x] 5.2 `MAX_SERVER_THREADS=64`：`_handle` 入口 `threading.active_count()` 超限响应 503，不堆积
- [x] 5.3 测试：monkeypatch 降至 2/4 后验证拒连与释放恢复；前端 503 时退化为轮询（配合 3.3 兜底心跳）

## 6. 端到端验证与收尾

- [x] 6.1 全量测试套件回归（tests/ 全部 dashboard 相关 + 既有 68 例不回归）
- [x] 6.2 150 spec 实测：浏览器挂载 5 分钟观察 `/api/specs` / `/api/overview` 请求间隔与 SSE payload 大小；dashboard API 单次响应 CPU 下降 ≥95%
- [x] 6.3 伪造 1000+ spec 目录压测 watcher 单轮时间与 /api/specs 响应时间（预算：<50ms 与 <300ms）
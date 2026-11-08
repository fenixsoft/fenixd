# SPEC 摘要内存索引

<!-- knowledge: capability=dashboard-spec-summary-index rev=3
     sources=spec/archive/2026-09-09-add-dashboard-incremental-data,spec/knowledge/_inbox/done/specs-api-read-path-triple-scan.md,spec/changes/fix-specs-api-latency -->

dashboard 服务端的 spec 摘要缓存与配置解析缓存：`/api/specs` 与 SSE 广播读索引，变更只重算受影响条目。

## 规则

- 每项目维护 `{spec_name → spec_summary}` 内存摘要索引，供 `/api/specs` 与 SSE 广播读取；惰性构建（首次 `/api/projects` 或 watcher 首轮扫描触发）。
- 每 spec 记录其依赖文件签名（tasks.md / specs 目录 / .spec.yaml / runs 目录 / verify-progress 文件，`mtime_ns+size` 键）：签名未变直接命中缓存（零文件读取）；签名变化只重算该 spec 一条；STATE.md 中该 spec 的条目字段（`status`/`error`/`frozen_until` 等派生字段来源）变化同样必须重算，不返回陈旧摘要。
- 全量重建仅用于首次构建与索引损坏场景；增量重算与全量重建的产出逐条等价。
- 取数与失效签名同趟：`get_with_signature()` 返回 `(摘要列表, 失效签名 | None)`，签名与响应体出自同一次扫描（同趟原子）；聚合素材全部取自本轮已驻留内存的数据——缓存命中条目复用索引存量 sigs、重算条目取新算 sigs，连同本轮 state/arch/runs 签名按同构结构聚合，聚合本身零额外 stat（仅排序与哈希）。同趟产物非跨请求 memo，不违反「签名现算禁跨请求 memo」纪律。state/arch 签名组件不可得（stat 失败等，含 STATE.md 消失窗口）时签名返回 None，消费方降级为无条件 200 路径（宁缺 304 不假 304）。`get()` 是它的薄包装（仅取列表位），watcher SSE 广播等既有消费方调用形态零变化。
- 失效签名独立计算入口 `invalidation_signature()` 不在生产路径消费：唯一消费方为一致性守卫测试——同一磁盘状态下它与 `get_with_signature()` 的聚合签名逐字节等值，作为聚合结构防漂移的锚定基准。
- 并发与锁粒度：`get()` / `state_snapshot()` / `invalidation_signature()` 各自持有本项目的槽锁（按项目根规范串分槽的 RLock，`dict.setdefault` 原子建槽、无需元锁）——同项目内三方法互斥（RLock 可重入，槽锁内重入同槽不死锁），跨项目读写互不阻塞。槽锁数量随项目数线性；项目删除后槽锁残留不清理（量级可忽略）。
- 配置解析签名缓存：`read_effective_config` 与 `read_spec_mode` 按 `(resolved_path, mtime_ns, size)` 缓存解析结果，mtime/size 未变不重读文件、不触发 YAML 解析；缓存不设条目上限（键与 spec 数线性）；文件写回（`write_config` 或直接编辑）后 mtime 变化自然失效。
- `cleanup_runs` 节流：对同一项目 60 秒内只实际执行一次清理，节流期内调用直接返回（幂等，无文件删除/目录遍历）。

## 代码锚点

- 主实现：`core/dashboard/data/summary.py`（SummaryIndex 与分槽锁表）
- 单源符号：`core/dashboard/data/summary.py:SummaryIndex`、`core/dashboard/data/summary.py:SummaryIndex._lock_for`
- 消费方：`core/dashboard/routes/spec_routes.py`（/api/specs 读端点）、`core/dashboard/watcher.py`（SSE 广播）
- 守卫测试：`tests/test_dashboard_index.py`（聚合签名与 invalidation_signature 等值、同槽重入不死锁）、`tests/test_specs_api_perf_guard.py`（跨项目互斥规模断言）

## 溯源

- 2026-09-09 2026-09-09-add-dashboard-incremental-data（spec/archive/2026-09-09-add-dashboard-incremental-data） — 建立内存摘要索引、配置解析签名缓存与 cleanup_runs 节流，`/api/specs` 从每请求 O(N) 全量重算改为读索引
- 已随 2026-09-21-fix-dashboard-read-path-performance 废除：STATE.md 签名变化即丢弃全部缓存并全量重建的失效语义（现按 spec 增量失效，规则由 dashboard-read-path-performance 能力页承载）
- 2026-11-08 specs-api-read-path-triple-scan（spec/knowledge/_inbox/done/specs-api-read-path-triple-scan.md） — 折叠同趟聚合与并发纪律：get_with_signature 取数签名同趟（实例级单锁治理为按项目分槽锁）、invalidation_signature 生产供给退役为守卫锚
- 2026-11-08 fix-specs-api-latency（spec/changes/fix-specs-api-latency/） — 本页同趟聚合与分槽锁规则的正式 SPEC 入库确认（`get_with_signature` 聚合签名、槽锁建槽与残留语义、invalidation_signature 唯一消费方=一致性守卫测试均以该 SPEC delta 为准定案）

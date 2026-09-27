# SPEC 摘要内存索引

<!-- knowledge: capability=dashboard-spec-summary-index rev=1
     sources=spec/archive/2026-09-09-add-dashboard-incremental-data -->

dashboard 服务端的 spec 摘要缓存与配置解析缓存：`/api/specs` 与 SSE 广播读索引，变更只重算受影响条目。

## 规则

- 每项目维护 `{spec_name → spec_summary}` 内存摘要索引，供 `/api/specs` 与 SSE 广播读取；惰性构建（首次 `/api/projects` 或 watcher 首轮扫描触发）。
- 每 spec 记录其依赖文件签名（tasks.md / specs 目录 / .spec.yaml / runs 目录 / verify-progress 文件，`mtime_ns+size` 键）：签名未变直接命中缓存（零文件读取）；签名变化只重算该 spec 一条；STATE.md 中该 spec 的条目字段（`status`/`error`/`frozen_until` 等派生字段来源）变化同样必须重算，不返回陈旧摘要。
- 全量重建仅用于首次构建与索引损坏场景；增量重算与全量重建的产出逐条等价。
- 配置解析签名缓存：`read_effective_config` 与 `read_spec_mode` 按 `(resolved_path, mtime_ns, size)` 缓存解析结果，mtime/size 未变不重读文件、不触发 YAML 解析；缓存不设条目上限（键与 spec 数线性）；文件写回（`write_config` 或直接编辑）后 mtime 变化自然失效。
- `cleanup_runs` 节流：对同一项目 60 秒内只实际执行一次清理，节流期内调用直接返回（幂等，无文件删除/目录遍历）。

## 溯源

- 2026-09-09 2026-09-09-add-dashboard-incremental-data — 建立内存摘要索引、配置解析签名缓存与 cleanup_runs 节流，`/api/specs` 从每请求 O(N) 全量重算改为读索引
- 已随 2026-09-21-fix-dashboard-read-path-performance 废除：STATE.md 签名变化即丢弃全部缓存并全量重建的失效语义（现按 spec 增量失效，规则由 dashboard-read-path-performance 能力页承载）

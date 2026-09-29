## Context

`core/admin_store.py` 的 `MAX_RECORDS=150` 裁剪（mutate 持锁段内 `del records[:-150]`，紧邻 `_write_unlocked` 调用）自 2026-09-01 起生效，设计意图是控活跃文件体积——但被裁记录直接丢弃，运维审计链断裂。`/api/overview` 是全 dashboard 最慢读端点（稳定 ~200ms），其调用方（概览页）被 2s SSE 心跳驱动，重复计算密集。

约束：
- `AdminStore` 全部写回路径经排他锁（`_trim_unlocked` 注释约定调用方持锁），归档追加必须同锁完成，避免裁剪与归档之间丢记录。
- dashboard 数据层读 `admin_alerts.json` 经 `core/dashboard/data/admin_alerts.py` → `AdminStore(project_root).read_all()`；归档读取走独立函数，不复用 `read_all`（避免污染既有调用方）。
- overview 聚合入口 `core/dashboard/data/summary.py` `overview(registry_projects)`；handler 为 `routes/project_routes.py` `_api_overview`（`routes/base.py` 仅 `_get_overview` JSON 包裹）。

## Goals / Non-Goals

**Goals**
- 运维历史可追溯：150 条池滚动出的记录进归档文件，滚动上限防归档无界。
- overview 重复计算归零：签名未变的重复请求不触发聚合。

**Non-Goals**
- 不做归档浏览前端界面（`?archived=1` API 出口先行，界面后续按需立项）。
- 不改 `MAX_RECORDS=150` 活跃上限本身（传输侧治理由 `add-dashboard-paging-and-etag` 承载）。
- 不给 `/api/specs` 等其它读端点加结果缓存（已有 SummaryIndex 增量缓存，边际收益小）。

## Decisions

### D1. 归档 = JSONL 旁路文件，追加写

选 JSONL（每行一条）而非 JSON 数组：追加写 O(1) 且无需读改写整文件（数组格式每次归档要全文件重写，150 条池高频裁剪下放大 IO）。路径 `<project_root>/.fenix/admin_alerts_archive.jsonl`，与活跃文件同目录。

*放弃的替代*：归档并入 `spec/archive/` 体系——运维记录非 SPEC 交付物，语义不符。

### D2. 归档写入失败软失败

归档是审计增强，不是主数据：写失败（磁盘满/权限）只记日志不抛出，保证裁剪主路径（活跃文件写回）永不被归档拖挂。与既有「监听绝不崩溃」的框架口味一致。

### D3. overview 缓存「TTL 或 签名」双键取或

单用 TTL：数据没变也每 2s 重算一次，浪费依旧。单用签名：项目集合不变+签名不变时永久命中，但签名计算本身要 stat 全部项目数据源（比聚合便宜 1~2 个量级，可接受）；TTL 兜底防御签名漏检（同 mtime_ns 同 size 的极端写回）。取「TTL 内直接命中 ∨ 签名相同直接复用」，两个条件任一满足即免重算。

### D4. 缓存放 handler 层，单槽即可

overview 响应全局一份（无 project 参数维度），单槽 `{sig, projects_key, computed_at, payload}` 足够；多槽/LRU 过度设计。线程安全经既有 handler 锁语义（读竞态最坏多算一次，无正确性风险——Python 单赋值原子，缓存读写不做锁亦可，但为防写撕裂用简单 `threading.Lock`）。

## Risks / Trade-offs

- **[归档文件与 .fenix gitignore]** `admin_alerts_archive.jsonl` 在 `.fenix/` 下属运行时数据，不进 git——与 `admin_alerts.json` 同待遇，无需声明交付物。
- **[裁剪高频时的归档写放大]** 活跃池 150 条高频滚动时每条记录恰好归档一次（append-only），无放大。
- **[overview 签名 stat 成本]** 5 项目 × 数据源文件数 stat，页缓存内 <5ms，比 200ms 聚合便宜 40 倍。

## Migration Plan

1. AdminStore 归档写入先行（纯增量，读侧零变化，单独合入即可发布）。
2. `?archived=1` 读出口 + 数据层读取函数。
3. overview 缓存最后接（复用签名函数——若 `add-dashboard-paging-and-etag` 的 `signature.py` 已合入则直接复用，否则本 SPEC 自带最小实现并在 design 注明合并时归一）。

## Open Questions

（无）

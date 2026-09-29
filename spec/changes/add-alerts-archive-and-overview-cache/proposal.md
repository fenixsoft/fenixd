## Why

Dashboard 数据侧两处规模隐患（2026-09-29 实测）：

- `admin_alerts.json` 的 150 条硬顶（`core/admin_store.py` `MAX_RECORDS`，写回时 `del records[:-150]` **直接丢弃**最旧记录）使运维时间线历史永久丢失——处置记录含 summary/actions_taken 等 Markdown 全文（avg 1.4KB/条、最大 6KB），是唯一的运维审计载体；且 5 个项目 × 150 条 × 1.4KB 聚合成 `/api/admin-activities` 单次 350KB 全量响应，传输成本直接由活跃文件体积决定。
- `/api/overview` 每次请求冷算全部注册项目的 `project_summary` 聚合（实测稳定 ~200ms，35s/70s 后重测无改善），而概览页由 2s SSE 心跳驱动重拉——约 10% 单核持续开销花在重复计算上。

## What Changes

- **裁剪改归档**：`AdminStore` 写回裁剪时，被移出的最旧记录**追加写入归档文件**（`admin_alerts_archive.jsonl`，每行一条）而非直接丢弃；归档文件自身设滚动上限（超限丢最旧），防止归档无界增长。读侧时间线（`get_admin_activities`）语义不变：仍只读活跃 150 条，页面展示与现状逐条一致。
- **归档只读出口**：`/api/admin-activities?archived=1` 返回归档记录（同构分页契约，供后续界面/CLI 消费）；本次不做前端归档浏览界面。
- **overview 结果缓存**：`/api/overview` 增加结果级 TTL 缓存——失效键为全部注册项目数据源签名（mtime/size 组合，复用既有失效键模式），命中窗口（≥2s，与 `REFRESH_HEARTBEAT` 对齐）内重复请求直接返回缓存结果，签名未变时即使 TTL 过期也直接复用。

## Capabilities

### New Capabilities

- `admin-alerts-archive`: 处置/告警记录裁剪时归档而非丢弃——归档文件格式、滚动上限、读侧时间线语义不变、`?archived=1` 只读出口。
- `dashboard-overview-cache`: `/api/overview` 签名失效 + TTL 双键结果缓存。

### Modified Capabilities

（无——`core/admin_store.py` 的裁剪行为属于存储层实现细节，归档能力以新 capability 承载；`/api/overview` 无既有能力 spec）

## Impact

- 后端存储层：`core/admin_store.py`（裁剪路径追加归档写入，须持锁内完成）。
- 后端数据层：`core/dashboard/data/admin_alerts.py`（归档读取函数）；`core/dashboard/routes/alert_routes.py`（`?archived=1` 参数）。
- 后端路由：overview handler（`core/dashboard/routes/base.py`）加结果缓存。
- 兼容性：无 BREAKING——活跃文件格式不变（仍是 JSON 数组）；归档文件为新增旁路；overview 响应结构不变（纯缓存加速）。
- 既有回归面：`fix-run-cleanup-attach-spec-archive` 的产物清理机制（归档文件属运行时数据不参与）；`add-dashboard-incremental-data` 的配置/签名缓存模式（复用不重造）。

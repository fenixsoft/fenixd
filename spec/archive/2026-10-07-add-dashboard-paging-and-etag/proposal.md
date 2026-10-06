## Why

Dashboard 读路径存在「无差别心跳 × 无上限全量载荷」叠加的传输浪费（2026-09-29 实测，Playwright tracing + curl 采样）：

- `REFRESH_HEARTBEAT = 2.0s` 的 SSE `refresh` 心跳（`watcher.py:53`）驱动 v3 页面全量重拉：运维页 `/activities` 挂 1 小时 ≈ **190MB** 网络流量（`/api/admin-activities` 350KB 原始/94KB gzip + `/api/alerts` 137KB 原始/12.5KB gzip，每 ~2s 一次，实测 22s 内重拉 9 次）。
- `/api/admin-activities` 跨项目聚合无分页无上限（`alert_routes.py` `_api_admin_activities`），单项目 `admin_alerts.json` 已达 150 条硬顶（avg 1.4KB/条、最大 6KB），5 项目聚合 350KB 只为前端渲染 15 条/页（前端分页，`activities/index.tsx` PAGE_SIZE=15）。
- `/api/specs?project=fenixd` 单次 341KB 原始/23.2KB gzip（52 specs 全量摘要），项目页 30s 心跳 + 每次进入 tab 全量重拉。
- 全部 GET 读端点无 ETag/304 通道（仅 `Cache-Control: no-cache`），数据未变时仍全量传输。

## What Changes

- **新增条件请求通道**：GET 读端点（`/api/overview`、`/api/specs`、`/api/specs/<spec>` 详情、`/api/admin-activities`、`/api/alerts`、`/api/config`）支持 ETag/If-None-Match 协商——ETag 由各项目数据源签名（mtime/size 组合）廉价计算，数据未变返回 304 空体。SSE 心跳照发，前端照常重拉，但未变数据的传输归零（350KB → ~200B header）。
- **新增服务端分页**：`/api/admin-activities` 与 `/api/specs` 支持 `page`/`page_size` 参数，响应带 `total`/`has_more`；缺省参数时保持现有全量行为（向后兼容，老调用方零改动）。前端运维页翻页改走 API 分页（替代前端全量分页），项目页 spec 表格维持全量摘要（分页能力供大项目使用，前端本次不改表格交互）。
- **SSE refresh 心跳语义收窄**（MODIFIED `dashboard-sse-refresh`）：带 `project` 字段的数据事件（state/detail/admin_activities）保持精确驱动；无 project 的 `refresh` 心跳对项目详情页降级为「仅触发条件请求校准」（304 未命中才真正重拉），跨项目聚合页（概览/运维）行为不变。

## Capabilities

### New Capabilities

- `dashboard-conditional-get`: GET 读端点 ETag/304 条件请求——数据源签名计算、协商命中返回 304、签名失效返回 200 全量。
- `dashboard-server-paging`: `/api/admin-activities` 与 `/api/specs` 服务端分页契约——page/page_size/total/has_more、缺省向后兼容、前端运维页翻页接 API。

### Modified Capabilities

- `dashboard-sse-refresh`: refresh 心跳对项目详情页从「全量重拉信号」降级为「条件请求校准信号」；带 project 的事件驱动语义不变。

## Impact

- 后端：`core/dashboard/routes/`（alert_routes/specs 相关 route 的 ETag 与分页参数）、`core/dashboard/watcher.py`（无改动或仅注释校准）、数据层签名函数（`core/dashboard/data/`）。
- 前端：`core/dashboard/static/src/pages/activities/index.tsx`（翻页走 API）、`core/dashboard/static/src/services/dashboard.ts`（请求层带 If-None-Match 与 304 处理）。
- 构建产物：`core/dashboard/static/dist/` 需重建（声明 reference，验证链读主树 dist）。
- 兼容性：无 BREAKING——缺省参数保持全量行为；304 对不感知 ETag 的调用方（curl 无 If-None-Match）零影响。
- 既有回归面：`2026-09-09-add-dashboard-incremental-data` 落地的 spec 表格增量 patch、`2026-09-10-add-activities-pagination` 的前端分页（被服务端分页替代，需迁移而非并存）、`2026-09-21-fix-dashboard-read-path-performance` 的 SummaryIndex 缓存（ETag 签名须复用其失效键模式，不得引入第二套扫描）。

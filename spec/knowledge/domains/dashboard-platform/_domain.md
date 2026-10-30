# 仪表盘服务
> 最后更新：2026-10-31 00:20 UTC+8

跨项目 Web 仪表盘的服务端与平台层：独立服务进程、实例生命周期、增量数据管线、实时会话、前端壳层基建、按需生成类任务、协作拓扑派生/跨项目聚合端点与指挥中心聚合。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [dashboard-server](dashboard-server.md) | dashboard 服务端 | 2026-10-03 04:59 |
| [fenix-dashboard-skill](fenix-dashboard-skill.md) | dashboard 技能入口 | 2026-10-03 04:59 |
| [dashboard-instance-lifecycle](dashboard-instance-lifecycle.md) | dashboard 实例生命周期（端口接管豁免/看门狗） | 2026-10-07 02:45 |
| [dashboard-push-restart](dashboard-push-restart.md) | pushed 终态自动重启 dashboard（内置 hook/去抖/静默跳过/逃生键） | 2026-10-07 02:36 |
| [dashboard-sse-refresh](dashboard-sse-refresh.md) | SSE 增量刷新 | 2026-10-07 02:25 |
| [v2-sse-bridge](v2-sse-bridge.md) | v2 SSE 桥（已随壳层退役） | 2026-10-03 04:59 |
| [dashboard-incremental-watcher](dashboard-incremental-watcher.md) | 增量数据 watcher | 2026-10-03 04:59 |
| [dashboard-log-offset-index](dashboard-log-offset-index.md) | 日志偏移索引 | 2026-10-03 04:59 |
| [dashboard-spec-summary-index](dashboard-spec-summary-index.md) | SPEC 摘要索引 | 2026-10-03 04:59 |
| [dashboard-data-modules](dashboard-data-modules.md) | 数据读取模块化 | 2026-10-03 04:59 |
| [dashboard-read-path-performance](dashboard-read-path-performance.md) | 读路径性能优化 | 2026-10-06 07:44 |
| [dashboard-overview-cache](dashboard-overview-cache.md) | /api/overview 结果缓存（TTL∨签名） | 2026-10-07 02:15 |
| [dashboard-conditional-get](dashboard-conditional-get.md) | GET 读端点条件请求（ETag/304） | 2026-10-07 02:25 |
| [dashboard-server-paging](dashboard-server-paging.md) | 读端点服务端分页 | 2026-10-07 02:25 |
| [dashboard-connection-limit](dashboard-connection-limit.md) | 连接数上限 | 2026-10-03 04:59 |
| [dashboard-live-session](dashboard-live-session.md) | 实时会话视图 | 2026-10-03 04:59 |
| [session-composer](session-composer.md) | 会话输入控件（补全/草稿/键盘适配） | 2026-10-03 04:59 |
| [project-architecture-diagram](project-architecture-diagram.md) | 项目架构图（archify 按需生成） | 2026-10-04 04:57 |
| [v2-data-adapters](v2-data-adapters.md) | v2 数据适配层（已随壳层退役） | 2026-10-03 04:59 |
| [v2-sdk-vendor](v2-sdk-vendor.md) | v2 vendored SDK（已随壳层退役） | 2026-10-03 04:59 |
| [v2-shell-router](v2-shell-router.md) | v2 shell 与 hash 路由（已随壳层退役） | 2026-10-03 04:59 |
| [v2-legacy-coexist](v2-legacy-coexist.md) | v2 与旧版并存机制（已随壳层退役） | 2026-10-03 04:59 |
| [topology-derivation](topology-derivation.md) | SPEC 协作拓扑派生端点（七阶段角色归列、KPI 五项口径、重试边仅连 attempt 链、多轮验证逐轮、交付终点按持久确证自适应、归档降级骨架） | 2026-10-30 23:11 |
| [collab-graph-aggregation](collab-graph-aggregation.md) | 跨项目角色级协作图谱聚合端点（复用 derive_topology 零第二套映射、project 筛选、下钻明细内嵌、归档计 KPI 不进图） | 2026-10-30 23:11 |
| [command-center-aggregation](command-center-aggregation.md) | 指挥中心后端聚合（KPI 四指标 7 日窗口径、组织网格静态花名册与汇报线、流水线五列桶映射、台账 50 条、收件箱只读装配复用 alert-resolve） | 2026-10-31 00:20 |

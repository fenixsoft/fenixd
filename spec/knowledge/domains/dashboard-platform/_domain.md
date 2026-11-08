# 仪表盘服务
> 最后更新：2026-11-08 21:00 UTC+8

跨项目 Web 仪表盘的服务端与平台层：独立服务进程、实例生命周期、增量数据管线、前端壳层基建、按需生成类任务与指挥中心聚合。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [dashboard-server](dashboard-server.md) | dashboard 服务端（含 API 验证取证纪律：禁破坏性 POST、404 分层、真实项目名探测、fixture 实例配方） | 2026-11-04 16:30 |
| [fenix-dashboard-skill](fenix-dashboard-skill.md) | dashboard 技能入口 | 2026-11-05 04:11 |
| [dashboard-instance-lifecycle](dashboard-instance-lifecycle.md) | dashboard 实例生命周期（端口接管豁免 unit/tmux 两支/看门狗、双向验证铁律、承载形态双轨重启协议 systemctl/respawn-window、陈旧进程判读含路由层 404/混代 500 签名） | 2026-11-08 20:53 |
| [dashboard-push-restart](dashboard-push-restart.md) | pushed 终态自动重启 dashboard（内置 hook/去抖/unit 缺席静默跳过/逃生键/tmux 托管盲态与收口方向） | 2026-11-06 18:13 |
| [dashboard-sse-refresh](dashboard-sse-refresh.md) | SSE 增量刷新 | 2026-10-07 02:25 |
| [dashboard-incremental-watcher](dashboard-incremental-watcher.md) | 增量数据 watcher | 2026-10-03 04:59 |
| [dashboard-log-offset-index](dashboard-log-offset-index.md) | 日志偏移索引 | 2026-10-03 04:59 |
| [dashboard-spec-summary-index](dashboard-spec-summary-index.md) | SPEC 摘要内存索引（同趟聚合签名、按项目分槽锁、配置解析缓存、cleanup_runs 节流） | 2026-11-08 21:00 |
| [dashboard-data-modules](dashboard-data-modules.md) | 数据读取模块化 | 2026-10-03 04:59 |
| [dashboard-read-path-performance](dashboard-read-path-performance.md) | 读路径性能治理（/api/specs 单趟读、SummaryIndex 增量失效、run 尾读、runs 清扫有界） | 2026-11-08 21:00 |
| [dashboard-overview-cache](dashboard-overview-cache.md) | /api/overview 结果缓存（TTL∨签名） | 2026-10-07 02:15 |
| [dashboard-conditional-get](dashboard-conditional-get.md) | GET 读端点条件请求（ETag/304；specs 走取数同趟型自含协商） | 2026-11-08 21:00 |
| [dashboard-server-paging](dashboard-server-paging.md) | 读端点服务端分页 | 2026-10-07 02:25 |
| [dashboard-connection-limit](dashboard-connection-limit.md) | 连接数上限 | 2026-10-03 04:59 |
| [project-architecture-diagram](project-architecture-diagram.md) | 项目架构图（archify 按需生成） | 2026-10-04 04:57 |
| [command-center-aggregation](command-center-aggregation.md) | 指挥中心后端聚合（KPI 四指标 7 日窗口径、组织网格五线静态花名册与汇报线、流水线五列桶映射、台账 50 条、收件箱只读装配复用 alert-resolve） | 2026-11-04 16:55 |

> 退役：2026-11-08 v2 amis 壳域五能力页（原 v2-shell-router / v2-data-adapters / v2-sdk-vendor / v2-sse-bridge / v2-legacy-coexist）已随 add-knowledge-anchor-lint-and-prune 退役收口删除，历史见 spec/archive/2026-09-04-v2-shell-hash-router、spec/archive/2026-09-04-v2-vendor-amis-sdk 等 2026-09-04/05 系列归档与 git 历史；tests/v2 冒烟基建与 v2_dev_server 现役，不在本退役批范围。

> 退役：2026-11-08 实时会话视图（原 dashboard-live-session）与会话输入控件（原 session-composer）已随「会话接入」分面退役批删除、SPEC 协作拓扑派生端点（原 topology-derivation）已随协作拓扑大屏退役批删除、跨项目角色级协作图谱聚合（原 collab-graph-aggregation）功能代码已随 v2 界面域退役消失本批补收口；历史见 spec/archive/2026-09-23-add-dashboard-live-session、spec/archive/2026-10-03-add-session-composer、spec/archive/2026-10-30-add-spec-topology-bigscreen、spec/archive/2026-10-30-add-collab-graph-bigscreen 与 git 历史。

## 症状速查

| 症状签名 | 能力页 |
| --- | --- |
| dsh web「重新连接中」重连环、WS 反复断连（close 4000 是下游症状勿查传输层） | [dsh-web-connection-baseline](../dashboard-frontend/dsh-web-connection-baseline.md)（dashboard-frontend 域） |
| 嵌入态 hash 深链丢失/挂载路径漂移（同源前缀代理挂载下） | [dashboard-embed-mount](../dashboard-frontend/dashboard-embed-mount.md)（dashboard-frontend 域） |
| 前端 rebuild 后改动不生效（拿到旧 bundle 验证新改动） | [page-container-chrome](../dashboard-frontend/page-container-chrome.md)（dashboard-frontend 域；hash goto 不重载文档，验证须整页 reload） |
| SSE 断开空窗/增量停摆 | [dashboard-sse-refresh](dashboard-sse-refresh.md)（30s 心跳兜底刷新、重连恢复增量） |
| dashboard 端口被占/实例疑似陈旧僵死 | [dashboard-instance-lifecycle](dashboard-instance-lifecycle.md)（陈旧进程判读、双轨重启协议） |
| SPEC 列表请求慢/超时（/api/specs 服务端延迟） | [dashboard-read-path-performance](dashboard-read-path-performance.md)（单趟同源聚合与分槽锁治理） |


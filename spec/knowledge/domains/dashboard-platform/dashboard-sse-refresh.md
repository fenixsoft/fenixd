# SSE 增量刷新

<!-- knowledge: capability=dashboard-sse-refresh rev=2
     sources=spec/archive/2026-09-09-add-dashboard-incremental-data,spec/archive/2026-10-07-add-dashboard-paging-and-etag -->

v3 SPA 前端的数据刷新模型：SSE 增量驱动 + 低频兜底心跳，轮询与 SSE 不叠加。

## 规则

- spec 数据流为 SSE 增量驱动：首屏经 `/api/specs` 建立本地 spec 摘要表；此后 `state` 增量事件进入本地 patch 队列（同 spec 1 秒内多事件只应用最新）；表格由本地表渲染，统计徽标由本地表推导。
- 增量事件只 patch 对应行，不触发全量列表重渲染；`{spec, summary:null}` 删除事件将该行从表格移除且排序保持。
- 带字段事件精确驱动：带 `project` 字段的数据事件（state/detail/admin_activities 等）直接驱动对应页面重拉渲染，不走条件请求降级路径。
- 无 `project` 字段的 `refresh` 心跳（`REFRESH_HEARTBEAT = 2.0s` 周期广播，兜底 daemon 状态/新项目发现等非文件变更场景）对项目详情页仅为条件请求校准信号：详情页收到心跳后执行条件请求（携带 If-None-Match），304 未命中（数据确实变化）才重拉渲染；跨项目聚合页（概览 `/overview`、运维 `/activities`）收到心跳后的重拉行为不变，未变数据的传输成本由 ETag/304 条件请求通道兜住。
- 轮询降为兜底：页面可见且 SSE 正常时 `/api/overview` 心跳间隔 ≥30s（30~60s 档）；`visibilitychange`（切后台再切回）触发一次立即校准请求。
- SSE 断线降级：连接断开（onerror/超时重连失败）时前端不进入空窗，心跳轮询按 30s 兜底刷新；重连成功后恢复增量模式。
- 列表检索防抖：spec 表格搜索/筛选输入在键入期间不触发后端请求，防抖 ≥300ms 后在本地摘要表内过滤；仅本地表为空（首屏未载入）时才回退请求 `/api/specs`。

## 关键行为

- 项目详情页可见且无项目数据变化：连续多个 refresh 心跳周期内，心跳触发的条件请求全部命中 304，无全量响应体传输，页面无重渲染。
- daemon 写 STATE.md 使项目 spec 状态变化：下一个 refresh 心跳到达时条件请求返回 200 全量，页面在心跳周期内（≤2s + 请求耗时）反映新状态。
- 概览页/运维页可见时 refresh 心跳到达：照常触发重拉请求，页码/滚动/页签状态保持。

## 溯源

- 2026-09-09 add-dashboard-incremental-data（spec/archive/2026-09-09-add-dashboard-incremental-data） — 前端由 2s 固定轮询（spec 列表页 3 秒 10 次请求）改为 SSE 增量驱动 + 30s 级兜底心跳 + visibilitychange 补刷 + 检索防抖
- 2026-10-07 add-dashboard-paging-and-etag（spec/archive/2026-10-07-add-dashboard-paging-and-etag） — refresh 心跳对项目详情页由「全量重拉信号」收窄为「条件请求校准信号」；带 project 事件与聚合页驱动语义保持不变

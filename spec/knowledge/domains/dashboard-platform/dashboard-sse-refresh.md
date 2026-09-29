# SSE 增量刷新

<!-- knowledge: capability=dashboard-sse-refresh rev=1
     sources=spec/archive/2026-09-09-add-dashboard-incremental-data -->

v3 SPA 前端的数据刷新模型：SSE 增量驱动 + 低频兜底心跳，轮询与 SSE 不叠加。

## 规则

- spec 数据流为 SSE 增量驱动：首屏经 `/api/specs` 建立本地 spec 摘要表；此后 `state` 增量事件进入本地 patch 队列（同 spec 1 秒内多事件只应用最新）；表格由本地表渲染，统计徽标由本地表推导。
- 增量事件只 patch 对应行，不触发全量列表重渲染；`{spec, summary:null}` 删除事件将该行从表格移除且排序保持。
- 轮询降为兜底：页面可见且 SSE 正常时 `/api/overview` 心跳间隔 ≥30s（30~60s 档）；`visibilitychange`（切后台再切回）触发一次立即校准请求。
- SSE 断线降级：连接断开（onerror/超时重连失败）时前端不进入空窗，心跳轮询按 30s 兜底刷新；重连成功后恢复增量模式。
- 列表检索防抖：spec 表格搜索/筛选输入在键入期间不触发后端请求，防抖 ≥300ms 后在本地摘要表内过滤；仅本地表为空（首屏未载入）时才回退请求 `/api/specs`。

## 溯源

- [2026-09-09 2026-09-09-add-dashboard-incremental-data](spec/archive/2026-09-09-add-dashboard-incremental-data/) — 前端由 2s 固定轮询（spec 列表页 3 秒 10 次请求）改为 SSE 增量驱动 + 30s 级兜底心跳 + visibilitychange 补刷 + 检索防抖

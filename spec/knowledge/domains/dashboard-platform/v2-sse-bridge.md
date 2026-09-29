# v2 SSE 桥

<!-- knowledge: capability=v2-sse-bridge rev=2
     sources=spec/archive/2026-09-05-v2-sse-bridge -->

v2 壳级 SSE 桥：把 `/api/stream` 帧转为 AMIS broadcast 事件供页面组件消费。

## 规则

- SSE 桥为壳级 custom 组件（挂在 app schema header，不随路由切换销毁）：EventSource 连接 `/api/stream`，每个 message 帧解析后以 `actionType: broadcast` 广播事件名 `sse:<type>`，data 为原始帧 JSON；hello 帧将 `evt.cid` 存入 `window.Bridge.cid`。
- 页面组件经 `onEvent` 监听 `sse:*` 广播消费数据（broadcast 跨组件可达），增量合并由页面侧 reload 语义承载，桥只负责帧转发。
- `refresh` 与 `state` 广播按事件名做 500ms 前缘节流（首帧立即广播，500ms 窗口内后续帧丢弃）；其他类型不节流——事件风暴不放大刷新。
- 断线显式告警：EventSource onerror 时 console.error 输出含 `[v2-bridge]` 标记的告警信息。
- 后端 SSE 协议零改动（hello/state/detail/run_meta/run_events/refresh/alerts/admin_activities）。
- 能力退役注记：v1/v2 dashboard 壳已整体移除（根路由直服 v3 SPA 首页），本页规则不再由现行代码承载，仅供追溯。

## 溯源

- 史前复原 — SSE 桥为 custom 组件 + broadcast 广播链路：桥端维护项目行基线，refresh/state 事件增量合并实现无感刷新
- [2026-09-05 2026-09-05-v2-sse-bridge](spec/archive/2026-09-05-v2-sse-bridge/) — 落地帧转 broadcast（`sse:<type>`）、cid 暴露、refresh/state 500ms 前缘节流与断线告警（史前的「桥端行基线增量合并」收敛为「广播原始帧、页面 onEvent→reload 消费」）
- 2026-09-02 git:ea88dd5a — v1/v2 dashboard 壳整体移除，SSE 桥随壳退役
- 2026-09-28 audit git:25bd6751 — 根路由改直服 v3 SPA（`/` 直接返回 `dist/index.html`，302 跳转取消），退役注记根路由表述纠偏

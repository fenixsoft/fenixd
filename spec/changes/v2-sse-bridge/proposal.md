## Why

dashboard 的数据实时性完全依赖全局 SSE(/api/stream,behavior.md §0)。AMIS 无原生 SSE 支持,需一个壳级桥接 custom 组件把 SSE 帧转为 AMIS broadcast 事件,各页面组件用 onEvent → reload 消费。这是 v2 数据流的核心通道(设计 §3)。

## What Changes

- 替换 `core/dashboard/static/v2/bridge.js` 占位:壳级 custom 组件实现(EventSource 连接、按 type 广播 `sse:*`、hello 帧存 cid、refresh/state 500ms 前缘节流、onerror 断线告警)
- 修改 `pages/app.json` header:SSE 桥 custom 组件挂壳级(不随路由切换销毁)
- overview 页临时探针 service(监听 sse:refresh 弹 toast)验证广播链路,后续 overview SPEC 移除
- 新增 tests/v2/bridge.spec.js、bridge-broadcast.spec.js

## Capabilities

### New Capabilities
- `v2-sse-bridge`: SSE 帧到 AMIS broadcast 的桥接通道

### Modified Capabilities

## Impact

- 修改 v2/bridge.js、pages/app.json;新增两个测试文件
- 后端 SSE 协议零改动(hello/state/detail/run_meta/run_events/refresh/alerts/admin_activities,behavior.md §0)

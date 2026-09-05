## Why

运行记录弹窗与 Admin 处置弹窗共享同一套实时流能力:SSE run watch 订阅、增量追加、粘性滚动、thinking_tokens 合并、关闭清理(behavior.md §3/§4)。AMIS 无对应组件,是 v2 最大的一块 custom JS(约 250 行,设计 §5)。

## What Changes

- 替换 `core/dashboard/static/v2/run-stream.js` 占位:`window.RunStream.mount(dom, props)` 实现(mode=run/admin 协议见计划头部;mode=admin 的状态机本 SPEC 一并实现,Task 9 只是接线)
- 修改 `pages/spec-detail.json`:时间轴节点点击的占位 Dialog 替换为 RunStream run 模式接入
- bridge.js 需暴露 cid(已在 v2-sse-bridge 落地:window.Bridge.cid)
- 新增 tests/v2/run-stream.spec.js

## Capabilities

### New Capabilities
- `v2-run-stream-modal`: 运行记录实时流 custom 组件(watch/增量/粘性滚动/token 合并/关闭清理/admin 状态机)

### Modified Capabilities
- `v2-spec-detail-page`: 时间轴节点点击 Dialog 从占位替换为 RunStream 接入(接线,不改本 SPEC 已验收行为)

## Impact

- 修改 run-stream.js、pages/spec-detail.json;依赖 behavior.md §3 的 watch 协议(POST/DELETE /api/runs/<id>/watch?cid=)与 §4 状态机

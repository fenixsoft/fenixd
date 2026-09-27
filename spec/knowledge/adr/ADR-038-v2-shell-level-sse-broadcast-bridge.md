# ADR-038：v2 事件架构——壳级 SSE 广播桥 + onEvent 重拉，增量数据流自管 EventSource

date: 2026-09-05
status: accepted

## Context

AMIS SDK 模式下页面如何消费 SSE：SDK 6.13 无 trackExpression；broadcast 是官方动作、纯 JSON 配置、事件不校验 scoped 整树可达（含弹窗内组件）。页面切换会销毁旧页面，桥必须活过页面生命周期。运行流（run_events）需要事件数据增量追加，「广播→重新拉 API」模式不适用。

## Decision

- SSE 桥挂壳级（app 组件壳）：帧转 `sse:<type>` broadcast；页面组件以 `onEvent: {"sse:xxx": reload/...}` 消费，不用 fetcher 缓存失效/trackExpression。
- 节流仅作用于 refresh/state：500ms 前缘触发、按事件名分别节流（首帧立即广播）；hello 不节流（用于存 cid）。
- 需要事件级增量的流（run_events 运行弹窗）不走 broadcast：消费组件自管 EventSource，快照先行（tail 拉取渲染）再 watch 增量，弹窗关闭即清理（DELETE watch + close ES）。

## Consequences

- 页面零手写事件逻辑，可由后续 SPEC 并行增量交付；页面级豁免 = 不挂 `onEvent sse:*` 监听即可（桥仍在广播，无害）。
- 双 EventSource 并存边界清晰：桥常驻壳级，run 流 ES 仅弹窗存活期存在。
- 断线由 es.onerror 显式 console.error 告警，不静默重连掩盖。

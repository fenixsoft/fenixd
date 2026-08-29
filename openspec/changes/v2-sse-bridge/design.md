## Context

链路已有源码级佐证(fork 查证):custom 组件 `props.onAction` 可发 broadcast(BroadcastAction.ts:51);broadcast 事件不校验 scoped,整棵渲染树任何 `onEvent:{"sse:xxx"}` 组件可达(renderer-event.ts:455-460);弹窗内组件同样可监听。桥必须放壳级——页面切换会销毁旧页面(App.tsx 以 key=activePage.id 重新 render)。

## Goals / Non-Goals

- Goals: SSE 帧 → `sse:<type>` 广播全链路可用;cid 暴露给 run 流(下一层);节流与老版一致
- Non-Goals: 各页面消费(后续 SPEC);run_events 增量消费(run-stream SPEC 自管,不走 broadcast)

## Decisions

- **broadcast + onEvent reload** 而非 fetcher 缓存失效/trackExpression(6.13 无 trackExpression;broadcast 官方支持、配置为纯 JSON)
- **500ms 前缘节流仅作用于 refresh/state**(老版行为,behavior.md §0);hello 不节流(存 cid)
- **节流键**:按事件名分别节流,前缘触发(首帧立即广播)
- **测试探针**:overview 页临时放监听 sse:refresh 弹 toast 的 service;watcher.py 1s 扫描天然产生 refresh 帧,15s 内必到
- **断线自检**:es.onerror 时 console.error 显式告警(设计 §8 风险对策)

## Risks / Trade-offs

- app.json 内字符串形式 onMount 在 SDK 模式的执行语义需实测;不生效则退路:app.js 里用 `amisRequire('amis').Renderer` 全局注册 custom 渲染器(计划 Task 3 Step 3 注明,实现等价)

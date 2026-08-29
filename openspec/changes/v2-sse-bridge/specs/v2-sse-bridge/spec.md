## ADDED Requirements

### Requirement: SSE 帧转为 broadcast 事件

桥组件连接 `/api/stream`,每个 message 帧解析后以 `actionType: broadcast` 广播事件名 `sse:<type>`,data 为原始帧 JSON。hello 帧将 `evt.cid` 存到 `window.Bridge.cid`。

#### Scenario: hello 帧到达并暴露 cid
- **WHEN** 访问 /v2/ 任一页面,等待 hello 帧
- **THEN** `window.BridgeTest.lastEvent.type === 'hello'` 且 `window.Bridge.cid` 为非空字符串

#### Scenario: 页面组件可监听广播(跨组件可达)
- **WHEN** 页面内有组件声明 `onEvent: {"sse:refresh": [...toast 动作]}`(测试探针)
- **THEN** watcher 心跳产生的 refresh 帧触发该 toast(15s 内)

### Requirement: refresh/state 帧前缘节流

refresh 与 state 广播按事件名做 500ms 前缘节流(首帧立即广播,500ms 窗口内的后续帧丢弃);其他类型不节流(behavior.md §0 与老版一致)。

#### Scenario: 事件风暴不放大刷新
- **WHEN** 服务端 1s 内产生多次 refresh
- **THEN** 广播次数 ≤ 2(前缘 + 窗口过缘后一次),`window.BridgeTest.reloadCount` 反映节流后数量

### Requirement: 断线显式告警

EventSource onerror 时 console.error 输出含 `[v2-bridge]` 标记的告警信息。

#### Scenario: 断线可观测
- **WHEN** SSE 连接异常断开
- **THEN** console 出现 `[v2-bridge] SSE 连接异常` 告警

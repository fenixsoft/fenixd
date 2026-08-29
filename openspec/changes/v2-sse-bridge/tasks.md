# Tasks: v2-sse-bridge

实现依据(实施 agent 必读,代码以计划为准):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 3」节(bridge.js 完整代码、header 挂载 JSON、两个测试文件)
- SSE 协议:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md §0

## 1. 测试先行

- [ ] 1.1 写 tests/v2/bridge.spec.js(hello 帧 → BridgeTest.lastEvent.cid 非空)并跑,确认 FAIL
- [ ] 1.2 写 tests/v2/bridge-broadcast.spec.js(探针 toast broadcast-ok)备用

## 2. 桥实现

- [ ] 2.1 按 plan Task 3 Step 3 实现 bridge.js(EventSource、广播、cid 存储、500ms 前缘节流、onerror 告警);pages/app.json header 换为 SSE 桥 custom
- [ ] 2.2 bridge.spec.js PASS;若字符串 onMount 不生效,按 plan 注明的退路(app.js 注册 Renderer)实现并记录
- [ ] 2.3 overview 页 body 临时加探针 service(注释标注 Task 5 移除),bridge-broadcast.spec.js PASS

## 3. 提交

- [ ] 3.1 `git add core/dashboard/static/v2/bridge.js core/dashboard/static/v2/pages/app.json tests/v2/ && git commit`(信息:`v2-bridge: SSE 桥 custom 组件 + broadcast 广播链路`)

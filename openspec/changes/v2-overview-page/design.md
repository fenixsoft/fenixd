## Context

componentId 契约(计划头部):ov-stats 响应 sse:state + sse:refresh;ov-projects 响应 sse:state。行为规格 §0:state 帧触发 overview 视图重拉,500ms 节流由桥处理。API 字段权威:behavior.md §1。

## Goals / Non-Goals

- Goals: 统计块与项目卡片渲染真实数据;启停删按钮走老版同款端点(POST /api/projects/<name>/start|stop、DELETE /api/projects/<name>);SSE 触发重拉可被测试观测
- Non-Goals: SPEC 列表(下一 SPEC);告警横幅(Task 11)

## Decisions

- **service + adaptor 模式**:api.adaptor 内调 `window.Adapters.adaptOverview/adaptProjects`,页面 JSON 不做字段逻辑
- **http 动作按钮模式定为样板**:confirmText → ajax → toast → reload componentId,后续页面行内按钮复用(计划 Task 5 Step 4 代码逐字)
- **SSE 观测**:bridge.js 的 reloadCount 计数器纯测试辅助,不影响业务
- **探针移除**:ov-stats 起真实监听后,临时 toast 探针使命结束

## Risks / Trade-offs

- 项目名/统计键在测试中来自环境实况(fixture),写测试时用真实项目名替换占位符

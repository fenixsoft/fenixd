## Why

壳级告警横幅是跨页面的全局能力(所有路由可见,响应 sse:alerts);运维记录页(admin 活动时间线+跨项目页签)响应 sse:admin_activities。这两个覆盖 v2 剩余两个视图,完成功能全集(设计 §4)。

## What Changes

- 修改 `pages/app.json` header:追加 alert-banner service(拉 /api/alerts,响应 sse:alerts;可点开 Dialog 列表,单条标记已处理 POST /api/alerts/<id>/handled,全部清空 POST /api/alerts/clear)
- 新增 `pages/activities.json`:跨项目页签(全部/各项目,?project= 参数差异 behavior.md §7)+ Timeline(act-timeline,响应 sse:admin_activities)
- 新增 tests/v2/activities-alerts.spec.js

## Capabilities

### New Capabilities
- `v2-alerts-activities`: 壳级告警横幅 + 运维记录页

### Modified Capabilities
- `v2-shell-router`: header 增加 alert-banner(不改壳行为)

## Impact

- 修改 pages/app.json;新增 pages/activities.json 与测试;依赖 v2-data-adapters、v2-sse-bridge

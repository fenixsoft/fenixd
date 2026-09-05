## Why

概览页是 v2 第一个完整页面:验证「页面 JSON + adapters + SSE 广播刷新」三者协作的端到端通路,其「service + onEvent reload + http 动作按钮」模式是后续页面的样板(计划 Task 5)。

## What Changes

- 新增 `core/dashboard/static/v2/pages/overview.json`:两个 service(ov-stats 拉 /api/overview、ov-projects 拉 /api/projects)+ 统计卡 grid + 项目 cards(启动/停止/删除按钮,confirm + ajax 动作)
- 移除 Task 3 的临时探针 service(broadcast-ok)
- app.js 改造为页面 JSON 合并加载(fetch pages/*.json 按 url 前缀合并,404 容错)——此改造在 overview SPEC 内一并完成,后续页面 SPEC 依赖它
- bridge.js 增加 reloadCount 测试辅助(sse:state/refresh 自增)
- 新增 tests/v2/overview.spec.js、overview-sse.spec.js

## Capabilities

### New Capabilities
- `v2-overview-page`: 概览页(统计块、项目卡片、生命周期控制、SSE 重拉)

### Modified Capabilities

## Impact

- 新增 pages/overview.json;修改 app.js、bridge.js、pages/app.json(移除探针)
- 后端零改动

## Why

v2 各页面要用 AMIS JSON 直接消费现有 `/api/*` 响应,但响应字段与 AMIS 期望的结构(crud items、页面数据域)有差异;且老版多个行为(生命周期排序、fix- 树分组、三级回退)是纯函数逻辑,应收敛到一个 adapters.js 以便 node 单测(计划 Task 4)。行为唯一权威:behavior.md §1/§2/§6。

## What Changes

- 替换 `core/dashboard/static/v2/adapters.js` 占位:UMD 模块(浏览器挂 window.Adapters,node 直接 require),10 个导出:SPEC_LIFECYCLE、adaptSpecs、adaptOverview、adaptProjects、adaptSpecDetail、adaptAlerts、adaptActivities、adaptConfig、buildConfigPayload、validateChain
- 新增 tests/v2/adapters.test.mjs(node:test)与 tests/v2/fixtures/api-samples.json(真实 API 响应样本)

## Capabilities

### New Capabilities
- `v2-data-adapters`: API 响应到 AMIS 数据结构的适配纯函数集

### Modified Capabilities

## Impact

- 修改 v2/adapters.js;新增 tests/v2/ 下 fixture 与单测
- 后端 API 零改动;字段名逐字以 behavior.md §1 为准

## Why

v2 需要一个可运行的应用壳:AMIS embed + hash 路由(带参数路由与 query 深链)+ Playwright 测试基建。后续所有页面 SPEC 都在此壳上加页面 JSON,SSE 桥与验收脚本依赖本 SPEC 的壳与测试设施(计划 Task 2)。

## What Changes

- 新增 `core/dashboard/static/v2/index.html`(引 sdk/adapters/bridge/run-stream/app 五个 JS,CSS 用 sdk+dark 主题)
- 新增 `core/dashboard/static/v2/app.js`:hash 路由解析(`window.V2.route()`)+ embed 初始化(5 个路由模式,behavior.md §8)+ 页面 JSON 合并加载(fetch pages/*.json 深合并进 app schema,404 容错)
- 新增 `core/dashboard/static/v2/pages/app.json`:app 组件壳(8 个页面条目含参数路由,页面 body 暂空)
- 三个占位 JS:adapters.js/bridge.js/run-stream.js(空对象,后续 SPEC 替换)
- 新增 `tests/v2/`:Playwright 基建(package.json、playwright.config.js baseURL=127.0.0.1:8787、smoke.spec.js)

## Capabilities

### New Capabilities
- `v2-shell-router`: v2 应用壳与 hash 路由;Playwright 冒烟基建

### Modified Capabilities

## Impact

- 新增 `core/dashboard/static/v2/` 下 6 个文件与 `tests/v2/` 目录
- 不改后端、不改老版 static

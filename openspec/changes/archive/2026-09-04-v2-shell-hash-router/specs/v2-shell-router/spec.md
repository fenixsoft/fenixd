## ADDED Requirements

### Requirement: hash 路由解析与参数路由

`window.V2.route()` 解析 location.hash 为 `{page, params, query, path}`;支持 5 个模式:`#/overview`、`#/project/:name`、`#/spec/:project/:name`、`#/config[/:project]?tab=`、`#/activities[/:project]`;缺省 hash 解析为 overview。

#### Scenario: 参数路由解析
- **WHEN** 访问 `#/spec/demo/add-login`
- **THEN** `V2.route()` 返回 page=spec-detail、params=["demo","add-login"]

#### Scenario: 缺省路由
- **WHEN** 访问 `/v2/index.html`(无 hash)
- **THEN** 解析为 overview 页且 AMIS 壳渲染出侧边导航(含"概览"菜单项)

### Requirement: 页面 JSON 合并加载

app.js 构建期 fetch `pages/*.json`(带防缓存参数)按 url 前缀合并进 app schema;单个页面文件缺失不阻断整体加载。

#### Scenario: 缺失页面容错
- **WHEN** pages/ 目录下某页面 JSON 尚未创建(404)
- **THEN** 壳照常加载,无未捕获异常,对应路由渲染空 page

### Requirement: Playwright 冒烟基建

tests/v2/ 具备可运行的 Playwright 环境(package.json、playwright.config.js baseURL=http://127.0.0.1:8787、chromium 已装)。

#### Scenario: 冒烟测试通过
- **WHEN** `cd tests/v2 && npx playwright test smoke.spec.js`
- **THEN** PASS(访问 /v2/index.html#/overview 后 #root 非空)

#### Scenario: 老版并存不受影响
- **WHEN** 访问 `/` 与 `/v2/index.html` 各页面路由并收集 pageerror
- **THEN** 老版正常渲染;v2 各路由无非由缺页面导致的 JS 错误

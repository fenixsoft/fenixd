# v2 Shell 与 Hash 路由

<!-- knowledge: capability=v2-shell-router rev=2
     sources=spec/archive/2026-09-04-v2-shell-hash-router -->

v2 应用壳的 hash 路由解析、参数路由与页面 JSON 合并加载契约。

## 规则

- `window.V2.route()` 解析 location.hash 为 `{page, params, query, path}`，支持 5 个路由模式：`#/overview`、`#/project/:name`、`#/spec/:project/:name`、`#/config[/:project]?tab=`、`#/activities[/:project]`；缺省 hash 解析为 overview。
- AMIS embed 页面按路由挂载；项目作用域经路由参数与 localStorage 全局选择器传递。
- 页面 JSON 合并加载：壳构建期 fetch `pages/*.json`（带防缓存参数）按 url 前缀合并进 app schema；单个页面文件缺失（404）不阻断整体加载，对应路由渲染空 page，壳照常加载无未捕获异常。
- Playwright 冒烟基建：`tests/v2/` 具备可运行环境（package.json、playwright.config.js 的 baseURL 指向 `http://127.0.0.1:8787`、chromium 已装）；冒烟以「访问 `#/overview` 后 `#root` 非空」为准。
- 能力退役注记：v1/v2 dashboard 壳已整体移除（根路由直服 v3 SPA 首页），本页规则不再由现行代码承载，仅供追溯（`tests/v2/` 冒烟基建目录仍留存）。

## 溯源

- 史前复原 — v2 壳层 hash 路由：embed 页面按路由挂载，项目作用域经路由参数与 localStorage 全局选择器传递
- 2026-09-04 2026-09-04-v2-shell-hash-router（spec/archive/2026-09-04-v2-shell-hash-router） — 落地 hash 路由解析（5 模式含参数路由与深链）、页面 JSON 合并加载容错与 Playwright 冒烟基建
- 2026-09-02 git:ea88dd5a — v1/v2 dashboard 壳整体移除（根路由 302 到 v3），本能力随壳层退役
- 2026-09-28 audit git:25bd6751 — 根路由改直服 v3 SPA（`/` 直接返回 `dist/index.html`，302 跳转取消），退役注记根路由表述纠偏

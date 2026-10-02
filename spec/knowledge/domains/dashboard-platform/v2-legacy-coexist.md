# v2 与旧版并存机制

<!-- knowledge: capability=v2-legacy-coexist rev=2
     sources=spec/archive/2026-09-05-fix-fix-v2-shell-hash-router -->

老版 dashboard 与 v2 壳并存互不影响的存在性契约与确定性回归锁定。

## 规则

- 老版 dashboard 与 v2 壳并存互不影响：`GET /` 老版入口页在停留老版文档时 `#main` 与 `#btn-overview` 可见且正常渲染；切换 `/v2/index.html#/overview` 后 v2 壳 `#root` 正常渲染；两文档各自独立，无整页跳出、无字体 404、无控制台错误。
- v2 导航链接经 `fixNavHrefs` 改写为 hash 形态，页内导航不整页跳离当前文档。
- 并存场景回归为确定性断言：`tests/v2/verify-fix.spec.js` 的 `legacy-dashboard-unaffected` 场景先 `GET /` 停留老版页、显式等待 `#main` 与 `#btn-overview` 可见（带超时）后再切 v2 壳，规避陈旧验证快照导致的误判。
- 能力退役注记：v1/v2 dashboard 壳已整体移除（`GET /` 不再服务老版入口，根路由直服 v3 SPA 首页），并存语义随双壳退役，本页规则仅供追溯。

## 溯源

- 2026-09-05 2026-09-05-fix-fix-v2-shell-hash-router（spec/archive/2026-09-05-fix-fix-v2-shell-hash-router） — 将「老版并存不受影响」残留验证场景硬化为确定性回归（显式等待 + 零 404/零 console error 断言），补齐父变更（children 分组侧边栏、fixNavHrefs hash 改写、webfont 补齐）的验证确定性
- 2026-09-02 git:ea88dd5a — v1/v2 dashboard 壳整体移除（根路由 302 到 v3），并存语义退役
- 2026-09-28 audit git:25bd6751 — 根路由改直服 v3 SPA（`/` 直接返回 `dist/index.html`，302 跳转取消），退役注记根路由表述纠偏

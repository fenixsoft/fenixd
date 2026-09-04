# Design: 锁定 fix-v2-shell-hash-router 残留的「老版并存」验证场景

## Context

`fix-v2-shell-hash-router` 的验证报告（`.fenix/verify-progress/fix-v2-shell-hash-router/report.json`）
共 12 个场景：11 通过、1 失败（`fix-legacy-dashboard-unaffected`）。失败断言原文为：

> 在老版入口页（GET / 的 #main、#btn-overview）断言其可见后再切到 v2 壳，两者各自正常渲染。

实测失败原因为**陈旧快照**：报告时间戳 `05:15:38` 早于修复提交 `be8f251`（`11:41`），彼时老版 `#main`/
`#btn-overview` 因时序未渲染即被断言；当前代码（修复已落地）下，直接 `GET /` 停留老版页时二者均正常可见
（`#main` 见 `core/dashboard/static/index.html:35`，`#btn-overview` 见 `:25`）。

## 根因与对策

- **根因**：验证场景断言缺乏「停留老版页、显式等待元素可见」的时序保证，陈旧快照下整页文档未就绪即超时。
- **对策**：在 `tests/v2/verify-fix.spec.js` 中将 `legacy-dashboard-unaffected` 改为：
  1. `page.goto(BASE + '/')` 后 `waitForSelector('#main', {state:'visible'})`；
  2. `expect(page.locator('#btn-overview')).toBeVisible()`；
  3. 再 `page.goto(BASE + '/v2/index.html#/overview')` 并断言 `#root` 可见。
  使「老版并存不受影响」成为确定性、可复现的回归。

## 不改动产品代码的依据

- hash 路由解析（`app.js:19-34`）、参数路由表（`app.js:11-17`）在当前代码正确；
- 侧边栏 hash 链接改写（`app.js:49-56` 的 `fixNavHrefs` + MutationObserver）已生效，导航不再整页跳出；
- webfont 已补齐于 `v2/thirds/@fortawesome/fontawesome-free/webfonts/`，无 404。
故本 SPEC 仅做验证确定性化，不引入产品代码改动。

## 风险 / 权衡

- 仅调整测试断言时序，无产品回归面；行为契约不变（老版与 v2 并存正确）。

# Proposal: 修复 fix-v2-shell-hash-router 验证中残留的「老版并存」场景

## Why

`fix-v2-shell-hash-router` 的验证报告（`.fenix/verify-progress/fix-v2-shell-hash-router/report.json`，
时间戳 `2026-08-29T05:15:38`，早于修复落地提交 `be8f251` 11:41）中仅剩 1 个失败场景
`fix-legacy-dashboard-unaffected`：断言老版入口页（`GET /` 的 `#main`、`#btn-overview`）在停留老版页时
可见，再切到 v2 壳后各自正常渲染。该失败是修复落地前的**陈旧快照**——当前工作区代码已含修复，
实测老版 `#main`/`#btn-overview` 正常渲染、v2 壳照常加载、零 404/console error。

本 SPEC 据此落实「老版 dashboard 与 v2 壳并存不受影响」这一残留场景的确定性回归锁定，使验证可复现通过。

## What Changes

- 在 `tests/v2/verify-fix.spec.js` 中将 `legacy-dashboard-unaffected` 场景**硬化为确定性断言**：先 `GET /`
  停留老版页、显式等待 `#main` 与 `#btn-overview` 可见（带超时）后再切到 v2 壳，规避陈旧快照导致的误判。
- 不改动任何产品代码：parent 修复（children 分组侧边栏 + `fixNavHrefs` 改写 hash 链接 + webfont 补齐）
  已使 hash 路由、参数路由、导航深链、老版并存全部正确；本 SPEC 仅补齐验证的确定性。

## Impact

- **测试**：`tests/v2/verify-fix.spec.js` 的 `legacy-dashboard-unaffected` 场景确定性化
- **行为**：无产品行为变化；残留验证场景转为可复现通过

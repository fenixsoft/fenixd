# Tasks: 修复 fix-v2-shell-hash-router 验证中残留的「老版并存」场景

## 1. 锁定残留验证场景（确定性回归）

- [x] 1.1 在 `tests/v2/verify-fix.spec.js` 中将 `legacy-dashboard-unaffected` 场景硬化：先 `GET /` 停留老版页、
  显式 `waitForSelector('#main')` 并断言 `#btn-overview` 可见，再切到 v2 壳断言 `#root` 可见，规避陈旧快照误判
- [x] 1.2 运行 `cd tests/v2 && npx playwright test verify-fix.spec.js` 确认 10/10 通过（含老版并存场景确定性通过）

## 2. 框架回归与打包

- [x] 2.1 运行框架单元测试（`python3 -m pytest tests/test_dashboard.py -q`）确认无回归

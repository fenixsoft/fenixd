# Proposal: add-app-badge — 首页徽标元素与点击文案切换

## Why

夹具静态小站需要一个可被自动化断言的交互元素：带稳定 testid 的徽标，点击
切换文案。它足够简单（单文件改动、确定性 DOM 断言），可被 web 验证场景完整
驱动「实现 → Playwright 验证 → 裁决」闭环，是集成测试环境验证 daemon 自动
闭环能力的最小夹具 SPEC。

## What Changes

- `index.html` 在 `#app-root` 内新增徽标元素 `<span data-testid="app-badge">`，
  初始文案「服务正常」；点击后文案切换为「已切换」，再次点击切回
  「服务正常」。切换逻辑以页内内联脚本实现，保持单文件改动粒度。

## Capabilities

### New Capabilities

- `app-badge`: 首页徽标元素（`data-testid="app-badge"` 稳定锚）与点击文案
  切换交互。

# Tasks: v2-shell-hash-router

实现依据(实施 agent 必读,代码以计划为准):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 2」节(index.html、app.js 完整代码、app.json 骨架、测试代码)
- 路由模式串:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md §8

## 1. Playwright 基建

- [x] 1.1 创建 tests/v2/package.json、playwright.config.js(baseURL=http://127.0.0.1:8787)、smoke.spec.js(计划 Task 2 Step 1 逐字);npm install + playwright install chromium
- [x] 1.2 跑 smoke 确认 FAIL(index.html 未建)

## 2. 壳与路由

- [x] 2.1 写 index.html(计划 Task 2 Step 3 逐字)与三个占位 JS(`window.Adapters={};`/`window.Bridge={};`/`window.RunStream={};`)
- [x] 2.2 写 app.js hash 路由 embed(计划 Task 2 Step 3 完整代码)与 pages/app.json(8 页面条目骨架)
- [x] 2.3 跑 smoke 确认 PASS;三种参数路由(#/project/x、#/spec/p/s、#/config?tab=llm、#/activities)访问零 pageerror

## 3. 提交

- [x] 3.1 `git add core/dashboard/static/v2/ tests/v2/ && git commit`(信息:`v2-skeleton: AMIS 壳 + hash 路由 embed + Playwright 冒烟`)

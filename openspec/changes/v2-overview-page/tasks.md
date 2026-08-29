# Tasks: v2-overview-page

实现依据(实施 agent 必读,代码以计划为准):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 5」节(app.js 合并加载改造、overview.json、按钮动作、SSE 测试)
- 字段权威:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md §1

## 1. app.js 合并加载

- [ ] 1.1 app.js 改造:Promise.all fetch app.json + 5 个 pages/*.json(?t= 防缓存,404 catch 跳过),按 url 前缀合并后 embed(计划 Task 5 Step 1 代码)

## 2. 测试先行

- [ ] 2.1 写 tests/v2/overview.spec.js(统计块可见、真实项目名可见,占位符换实况项目名);跑确认 FAIL

## 3. 页面实现

- [ ] 3.1 实现 pages/overview.json:ov-stats(5 统计卡,sse:state+sse:refresh 监听)、ov-projects(cards+启停删按钮动作模式,计划 Task 5 Step 4 逐字);同时移除 Task 3 探针、bridge.js 加 reloadCount
- [ ] 2.2→3.2 overview.spec.js PASS

## 4. SSE 联动

- [ ] 4.1 写 tests/v2/overview-sse.spec.js(touch 项目 .fenix 文件触发 state 帧,断言 reloadCount ≥ 2);跑 PASS

## 5. 提交

- [ ] 5.1 `git add core/dashboard/static/v2/ tests/v2/ && git commit`(信息:`v2-overview: 概览页(统计块+项目卡片+启停删+SSE 重拉)`)

# Tasks: v2-data-adapters

实现依据(实施 agent 必读):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 4」节(测试代码、UMD 骨架、导出签名)
- 行为与字段权威:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md §1(API 字段表)、§2(列表/树/排序)、§6(配置/回退/链校验)

## 1. Fixture 与测试先行

- [ ] 1.1 curl 抓取 /api/overview、/api/specs?project=<有fix子spec的项目>、/api/alerts、/api/admin-activities、/api/config 存 tests/v2/fixtures/api-samples.json(单对象,键同端点名);与 behavior.md §1 字段表核对
- [ ] 1.2 写 tests/v2/adapters.test.mjs(计划 Task 4 Step 2 的 5 个用例为基线,字段名按 fixture 实况落笔);跑确认 FAIL

## 2. 实现

- [ ] 2.1 实现 adapters.js:SPEC_LIFECYCLE(behavior.md §2 逐字)、adaptSpecs(排序+fix 树)、adaptOverview/adaptSpecDetail(数字化)、adaptProjects/adaptAlerts/adaptActivities、adaptConfig(llm 兜底)、buildConfigPayload(三级回退)、validateChain(§6 规则)
- [ ] 2.2 node --test tests/v2/adapters.test.mjs 全绿;浏览器侧 window.Adapters 可用(index.html 已引)

## 3. 提交

- [ ] 3.1 `git add core/dashboard/static/v2/adapters.js tests/v2/ && git commit`(信息:`v2-adapters: 数据适配纯函数 + node 单测`)

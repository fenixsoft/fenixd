# Tasks: v2-project-list-page

实现依据(实施 agent 必读,代码以计划为准):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 6」节(crud 骨架、状态 mapping 示例、名称链接列、dropdown 三操作 JSON、测试代码)
- 行为权威:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md §2(列/过滤/树)、§5(Why/清除)、§1(字段)

## 1. 测试先行

- [x] 1.1 写 tests/v2/project.spec.js(表头/树形/操作按钮可见 + 关键词过滤,占位符换实况);跑确认 FAIL

## 2. 页面实现

- [x] 2.1 实现 pages/project.json:crud(spec-crud)+ 8 列 + filter + dropdown 操作 + error/Why 详情 Dialog(计划 Task 6 Step 3;树行展开配置按 6.13 实测)
- [x] 2.2 project.spec.js PASS;SSE 联动抽查(spec-crud 响应 sse:state)

## 3. 提交

- [x] 3.1 `git add core/dashboard/static/v2/pages/project.json tests/v2/ && git commit`(信息:`v2-project: SPEC 列表页(8 列+过滤+fix 树+行内操作)`)## 验证修复（第 2 轮失败）

- [x] 阅读 `openspec/changes/v2-project-list-page/verification-report.md`，定位「真实产品 Bug」并修复
- [x] 修复后重跑验证确认通过

## 验证修复（第 1 轮失败）

- [ ] 阅读 `openspec/changes/v2-project-list-page/verification-report.md`，定位「真实产品 Bug」并修复
- [ ] 修复后重跑验证确认通过

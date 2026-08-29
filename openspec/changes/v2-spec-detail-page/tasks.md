# Tasks: v2-spec-detail-page

实现依据(实施 agent 必读,代码以计划为准):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 7」节(service/adaptor、页签结构、detail 帧比对 script、时间轴点击占位 Dialog、测试代码)
- 行为权威:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md §1(详情字段)、§0(detail 帧)

## 1. 测试先行

- [x] 1.1 写 tests/v2/spec-detail.spec.js(验证卡可见 + 4 页签依次可点;真实 <project>/<spec> 落笔);跑确认 FAIL

## 2. 页面实现

- [x] 2.1 实现 pages/spec-detail.json(计划 Task 7 Step 3):spec-detail service、验证卡/进度/清单、4 页签、sse:detail 比对 script、时间轴点击占位 Dialog
- [x] 2.2 spec-detail.spec.js PASS;若截图/时间轴数据为空环境,用 fixme 标注对应断言并记录于测试注释

## 3. 提交

- [ ] 3.1 `git add core/dashboard/static/v2/pages/spec-detail.json tests/v2/ && git commit`(信息:`v2-spec-detail: 详情页(验证卡+4 页签+SSE detail 刷新)`)

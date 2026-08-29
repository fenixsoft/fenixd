# Tasks: v2-alerts-activities

实现依据(实施 agent 必读,代码以计划为准):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 11」节(header 横幅 JSON、activities.json、测试代码)
- 行为权威:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md §7(告警/运维记录)、§1(字段)

## 1. 测试先行

- [ ] 1.1 写 tests/v2/activities-alerts.spec.js(时间线可见;有告警环境的横幅用例,无告警则 test.fixme 注明);跑确认 FAIL

## 2. 实现

- [ ] 2.1 pages/app.json header 追加 alert-banner service(计划 Task 11 Step 3 JSON);实现 pages/activities.json(Tabs+Timeline)
- [ ] 2.2 activities-alerts.spec.js PASS

## 3. 提交

- [ ] 3.1 `git add core/dashboard/static/v2/ tests/v2/ && git commit`(信息:`v2-shell: 壳级告警横幅 + 运维记录页`)

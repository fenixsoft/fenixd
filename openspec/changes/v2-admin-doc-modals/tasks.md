# Tasks: v2-admin-doc-modals

实现依据(实施 agent 必读,代码以计划为准):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 9」节(admin Dialog JSON、文档 Dialog JSON、测试代码)
- 端点语义:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-behavior.md §1(spec-doc 404 语义)、§4(等待态文案)

## 1. 测试先行

- [ ] 1.1 写 tests/v2/admin-doc.spec.js(文档弹窗两分支 + admin 弹窗等待态与关闭清理);跑确认 FAIL

## 2. 接线实现

- [ ] 2.1 pages/project.json:呼叫 Admin Dialog 替换占位 toast(RunStream admin 接入 JSON 逐字);「文档」入口接 3 页签懒加载 Dialog
- [ ] 2.2 admin-doc.spec.js PASS

## 3. 提交

- [ ] 3.1 `git add core/dashboard/static/v2/pages/project.json tests/v2/ && git commit`(信息:`v2-admin-doc: Admin 处置弹窗接入 + SPEC 文档弹窗`)

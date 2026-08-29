# Tasks: v2-acceptance-suite

实现依据(实施 agent 必读):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 12」节(acceptance.spec.js 覆盖清单)
- 验收标准:docs/superpowers/specs/2026-08-29-amis-dashboard-v2-design.md §7

## 1. 验收脚本

- [ ] 1.1 写 tests/v2/acceptance.spec.js:深链(config?tab=、spec/:p/:s + 刷新保持)、老版冒烟(#tl-root)、双版列表行数对齐、run 弹窗三态抽查、admin 等待态+关闭退订(route 拦截)、全程 pageerror 断言
- [ ] 1.2 `cd tests/v2 && npx playwright test` 全绿;任何失败逐个修复或开 fix spec,不得跳过

## 2. 运行手册

- [ ] 2.1 写 tests/v2/RUNBOOK.md(启动/安装/fixme 清单/双版执行方式)

## 3. 提交与人工验收

- [ ] 3.1 `git add tests/v2/ && git commit`(信息:`v2-acceptance: 全量验收脚本 + 运行手册`)
- [ ] 3.2 向用户报告:请人工浏览 /v2/ 全功能(此为设计 §7 通过标准的一部分,不可跳过);用户确认前不开 cutover

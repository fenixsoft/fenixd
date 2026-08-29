# Tasks: v2-cutover-main-entry

实现依据(实施 agent 必读):
- 实施计划 docs/superpowers/plans/2026-08-29-amis-dashboard-v2.md「Task 13」节(改动行号与步骤)
- 设计 docs/superpowers/specs/2026-08-29-amis-dashboard-v2-design.md §2/§7

## 1. 前置确认(硬门槛)

- [ ] 1.1 确认三条件:v2-acceptance-suite 已完成且全绿;用户人工浏览 /v2/ 已通过;用户明确批准切换。任一不满足 → 停止,在 SPEC error 记「等待用户切换授权」并结束

## 2. 切换

- [ ] 2.1 新增 core/dashboard/static/legacy.html(复刻现 index.html,title 注明 legacy,引原 app.js/style.css;原文件不动)
- [ ] 2.2 server.py:225-226 根路径分支改 serve v2/index.html;新增 /legacy.html 分支(计划 Task 13 Step 2 代码)
- [ ] 2.3 新增 tests/v2/base-url.spec.js 对 / 跑核心冒烟(壳渲染、概览数据可见、零 pageerror)

## 3. 回归与提交

- [ ] 3.1 重启 dashboard 进程(touch .fenix/restart_request 走 supervisor 优雅重启协议)后 base-url.spec.js 全绿
- [ ] 3.2 `git add core/dashboard/server.py core/dashboard/static/legacy.html tests/v2/ && git commit`(信息:`v2-cutover: 主入口切换到 AMIS v2,老版保留 /legacy.html`)

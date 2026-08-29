## Context

切换是用户显式授权的动作:实施 agent 在执行本 SPEC 前必须确认「Task 12 全绿 + 用户人工浏览已通过 + 用户已批准切换」三条件(实施计划 Task 13 Step 1;设计 §2)。若条件不满足,停止并在 SPEC error 中注明等待用户确认。

## Goals / Non-Goals

- Goals: `/` serve v2;老版经 /legacy.html 可达;复跑验收确认
- Non-Goals: 删除老版文件(永不删除,回退保障);替换期开关 UI(设计 §9)

## Decisions

- **legacy.html 复制而非移动**:不动原 index.html/app.js,零回退风险
- **切换后复跑验收**:新增 base-url.spec.js 对 `/` 跑核心冒烟,确保 serve 路径正确
- **回退预案**:出现问题时将 server.py 根路径分支改回 index.html 即可(一行回退)

## Risks / Trade-offs

- 用户书签/链接打到 / 的体验变化:即本次切换的目的(经用户批准)

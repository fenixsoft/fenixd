## Why

v2 验收全绿(脚本全绿 + 用户人工浏览确认)后,把 dashboard 主入口 `/` 从老版 app.js 切到 v2;老版保留为 /legacy.html 以便回退。这是 v2 重构的收尾(设计 §2「替换 = 单独小提交」)。

## What Changes

- **BREAKING**(对 `/` 的默认体验): server.py 根路径 serve v2/index.html
- 新增 `core/dashboard/static/legacy.html`:复刻现 index.html 内容(title 注明 legacy),引原 app.js/style.css——原文件不动
- 修改 server.py:225-226:`path == "/"` 分支改 serve `v2/index.html`,新增 `/legacy.html` 分支
- 测试 baseURL 切换:核心冒烟对 `/` 复跑(RUNBOOK 记录)

## Capabilities

### New Capabilities
- `v2-cutover-main-entry`: 主入口切换与老版归档入口

### Modified Capabilities

## Impact

- 全计划唯一一处后端改动(2-3 行);老版行为经 /legacy.html 仍完整可用
- 前置:验收全绿 + 用户明确下达「替换」指令

# Tasks: add-admin-activity-view

## 1. admin-narrative-summary（admin 写叙述总结）

- [ ] 1.1 `core/agent_runner.py` administrator prompt 增加 `summary` 字段要求：人类可读叙述（诊断结论、处置时间线、结果、对人类的建议）
- [ ] 1.2 `core/admin_monitor.py:_invoke_administrator` 落盘 disposition 记录时透传 `summary`（disp.summary）到 admin_alerts.json；`AdminDisposition` 增加 summary 字段
- [ ] 1.3 `_read_admin_disposition` 解析 summary 字段（列表/字符串归一化）

## 2. 运维记录 API

- [ ] 2.1 `core/dashboard/data.py` 新增 `get_admin_activities(proot)`：从 admin_alerts.json 过滤 disposition，按时间倒序，未处理 escalation 关联置顶
- [ ] 2.2 `core/dashboard/server.py` 新增 `GET /api/admin-activities?project=<name>`（跨项目聚合时按项目分组），返回含 summary/actions/result/escalate/recommended_action/handled 的记录列表

## 3. 运维记录独立页面

- [ ] 3.1 `core/dashboard/static/index.html` 侧边栏新增"运维记录"入口 + 页面容器
- [ ] 3.2 `core/dashboard/static/app.js` 新增路由/渲染函数：时间线卡片（时间/spec/信号/叙述总结/动作/结果徽章/建议），未处理升级置顶高亮 + mark-handled 操作；旧记录无 summary 时降级显示结构化字段

## 4. 测试与验证

- [ ] 4.1 补 admin_disposition 含 summary 的单元测试（run_administrator 透传 + _read_admin_disposition 解析）
- [ ] 4.2 补 /api/admin-activities 测试（排序/置顶/空列表/缺 summary 降级）
- [ ] 4.3 运行 `python3 -m pytest tests/ -q` 全绿

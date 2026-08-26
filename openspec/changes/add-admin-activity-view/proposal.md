## Why

Administrator 自愈闭环已上线（检测困境 → 唤起 admin → 处置），但人类只能看到"未处理升级告警横幅"，无法了解 Administrator **到底做了什么、为什么、结果如何**。需要面向人类的 Administrator 活动界面：admin 每次处置后写一段可读总结，dashboard 以时间线展示，需人类决策时给出明确建议。

## What Changes

- **Administrator 叙述性总结**：admin 处置后除结构化 disposition 外，新增 `summary` 字段——人类可读的叙述（含诊断结论、处置时间线、结果、对人类的建议）。admin prompt 要求撰写。
- **Dashboard 独立"运维记录"页面**：展示全部 Administrator 活动（时间/事项/结果/建议），未处理升级告警置顶高亮并给出明确人工建议。
- **API**：新增 `/api/admin-activities`，返回按时间倒序的 admin 处置记录（含 `summary` 叙述 + 结构化字段 + 升级状态）。

## Capabilities

### New Capabilities

- `admin-narrative-summary`: Administrator 处置后撰写人类可读的叙述性总结（时间/事项/结果/人工建议），随处置记录落盘
- `admin-activity-view`: Dashboard 独立页面展示 Administrator 活动时间线与人工决策建议，未处理升级高亮

### Modified Capabilities

（无。openspec/specs/ 为空，全部为新增能力。）

## Impact

- **代码**：`core/agent_runner.py`（admin prompt + disposition 格式）、`core/admin_monitor.py`（disposition 记录带 summary）、`core/dashboard/data.py`、`core/dashboard/server.py`、`core/dashboard/static/app.js`、`core/dashboard/static/index.html`
- **数据格式**：`admin_disposition.json` 与 `admin_alerts.json` 的 disposition 记录新增 `summary` 字段（向后兼容，旧记录无该字段时界面降级显示结构化信息）
- **API**：新增 `/api/admin-activities`，不影响现有 `/api/alerts`

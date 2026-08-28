## Why

SPEC 右键菜单「呼叫 Admin 介入」目前呼叫成功后仅弹一条 toast（app.js `_ctxAdminInvoke`），用户无法直观看到 Administrator 是否已在处置、处置到什么程度。后台已有完整的处置记录数据源（`GET /api/admin-activities`）与全局 SSE 推送链路（FileWatcher → sse_hub），但两者未在呼叫场景打通，呼叫方处于"呼叫后两眼一抹黑"的状态。

## What Changes

- 点击「呼叫 Admin 介入」菜单项，呼叫成功（或 409 已在处置中）后自动弹出一个处置记录弹窗，不再只显示 toast。
- 弹窗内容为**该 SPEC 相关**的处置记录：复用运维记录视图的卡片渲染（叙述总结、处置动作、结果、状态标签），按记录的 `spec` 字段过滤（escalation/disposition 记录均携带 spec 字段）。
- 弹窗打开期间通过**SSE 实时推送**更新内容，复用运行时间轴查看 Agent 消息的同款机制（全局 `/api/stream` + watcher 文件变更广播），Admin 后台持续处置时弹窗内容自动刷新。
- 用户可随时关闭弹窗；关闭不影响 Admin 后台处置流程（呼叫信号已落盘，处置继续）。
- Dashboard 后端：`GET /api/admin-activities` 新增可选 `spec` 查询参数，支持按 SPEC 过滤；FileWatcher 增加对 `.fenix/admin_alerts.json` 的监听，变更时广播处置记录更新事件。

## Capabilities

### New Capabilities

- `admin-invoke-record-dialog`: 呼叫 Admin 后的处置记录弹窗能力，覆盖呼叫触发弹窗、按 SPEC 过滤展示、SSE 实时更新、可关闭且后台处置不受影响。

### Modified Capabilities

（无 —— 既有「呼叫 Admin 介入」菜单项的呼叫信号写入行为不变，仅其后置反馈从 toast 升级为弹窗，属本新能力范围；历史 change `add-spec-context-menu`、`add-admin-activity-view` 的能力行为均无 spec 级修改。）

## Impact

- `.fenix/core/dashboard/static/app.js`：`_ctxAdminInvoke` 后置行为改为打开弹窗；新增处置记录弹窗渲染与 SSE 事件处理；复用 `activityCard` 渲染与现有 modal 框架。
- `.fenix/core/dashboard/server.py`：`/api/admin-activities` 支持 `spec` 参数透传。
- `.fenix/core/dashboard/data.py`：`get_admin_activities` 增加可选 `spec` 过滤参数。
- `.fenix/core/dashboard/watcher.py`：监听 `admin_alerts.json` 变更并广播新事件类型（如 `admin_activities`）。
- 无数据库/外部依赖变更；`admin_alerts.json` 结构不变，纯读取侧扩展。

# add-admin-invoke-dialog — Design

## Context

- SPEC 右键菜单「呼叫 Admin 介入」实现在 `.fenix/core/dashboard/static/app.js` `_ctxAdminInvoke`（约 2616 行）：POST `/api/spec-admin-invoke` 成功后仅 `toast('已呼叫 Admin 介入检查')`，409 被当作错误抛出。
- 处置记录数据源：`.fenix/admin_alerts.json`（`AdminStore`，含 escalation/disposition 记录，均带 `spec` 字段）；`dashboard_data.get_admin_activities(project_root)`（data.py:74）已实现归并、未处理升级置顶，但无 spec 过滤。
- 端点 `GET /api/admin-activities?project=<name>` 已存在（server.py:591），前端运维记录视图（`view === 'activities'`，app.js:353-457 `renderActivities`/`activityCard`）已有完整渲染。
- SSE 链路：全局 `/api/stream`（app.js:220-239）→ 前端 `handleSSEEvent` 分发 `state/detail/run_meta/refresh/run_events/alerts`；后端 `FileWatcher`（watcher.py）定时扫描文件集，其 `_iter_project_files` **未包含** `admin_alerts.json`；run 弹窗的 `run_events` 增量推送（modalRunId + watch/unwatch）是"弹窗 + SSE 实时更新"的现成参考实现。
- 用户确认的需求口径：呼叫成功（含 409）后自动弹窗；仅显示该 SPEC 的记录；实时更新复用 timeline/Agent 消息查看的 SSE 机制；可关闭、后台处置不受影响。

## Goals / Non-Goals

**Goals**

- 呼叫后立即给用户可见的处置进度窗口（含"已在处置中"场景）。
- 处置记录变化实时反映到弹窗（SSE 推送驱动，非定时轮询）。
- 记录渲染与运维记录视图视觉一致（复用 `activityCard`）。

**Non-Goals**

- 不改变 `/api/spec-admin-invoke` 呼叫信号机制本身（admin_invoke_request.json 写入逻辑不动）。
- 不做弹窗内的操作能力（标记已处理、重试等），弹窗只读；处置动作仍在运维记录视图与后台进行。
- 不改造 run_events 增量推送协议，仅新增一种广播事件类型。

## Decisions

**D1 — SSE 更新采用「广播通知 + 前端重新拉取」而非服务端全量推送数据。**
FileWatcher 检测到 `admin_alerts.json` 变更时广播轻量事件 `{type: "admin_activities", project: <name>}`（不带数据）；前端弹窗打开且 project 匹配时重新 `GET /api/admin-activities?project=<name>&spec=<name>` 并重渲染。
理由：与现有 `refresh` 事件模式一致（watcher 广播、前端自行拉取），避免在 watcher 里重复 get_admin_activities 的归并逻辑；处置记录量级小（单文件 JSON），重拉成本可忽略；且天然遵守多项目隔离（弹窗只关心当前 project）。备选的"watcher 直接推送 activities 数据"需要 watcher 持有 data 层归并逻辑并区分 project/spec，复杂度不值。

**D2 — 服务端过滤：`get_admin_activities` 增加 `spec: Optional[str]` 参数，端点透传。**
在 data.py 归并/置顶逻辑之后、返回之前按 `rec.get("spec") == spec` 过滤，保证置顶语义先于过滤生效。备选"前端过滤全量结果"会把全项目记录流量带给每个弹窗，且与"弹窗只看该 SPEC"的需求错位。

**D3 — 409 视为弹窗触发成功。**
`_ctxAdminInvoke` 将 409（已有处置进行中）与 2xx 一同进入"打开弹窗"分支。理由：409 本身即说明 Admin 已在处置，正是用户最需要看到处置进度的场景。备选"409 报错提示"维持了现状的语义盲区，与本需求相悖。

**D4 — 复用现有 modal 框架 + `activityCard` 渲染，弹窗状态用模块级变量管理。**
新增 `modalAdminSpec` 状态（与 `modalRunId` 同模式）：打开时记录 project/spec 并立即拉取渲染；SSE 事件到达时仅当弹窗打开才响应；关闭时清空状态。渲染直接复用运维记录视图的 `activityCard`/状态标签 CSS，不新建样式体系。空态显示「该 SPEC 暂无处置记录」。

**D5 — watcher 监听 `admin_alerts.json` 放入现有扫描循环，不新建线程。**
在 `_iter_project_files` 增加该文件（kind 用新值 `admin` 或复用 `logs` 语义外的新 kind），`scan_once` 对比 mtime 后调用新 handler 广播。理由：复用既有 mtime 扫描机制（与 run/state 一致），不引入新线程/文件句柄管理。

## Risks / Trade-offs

- [弹窗打开期间 SSE 断线（onerror 自动重连窗口期）错过广播] → 重连成功后 `handleSSEEvent` 现有重拉机制兜底；弹窗打开状态下 onopen 时额外重拉一次该 SPEC 记录。
- [`admin_alerts.json` 写入频繁（每次 mark_handled 等均触发）导致广播风暴] → 记录量级极小（单项目手工级操作频率），且广播为轻量事件；与 state 扫描同一节拍，无额外压力。
- [409 弹窗改变了原 toast 错误语义] → 409 响应体含明确 error 文案，弹窗顶部可附带「已有处置进行中」提示行，避免用户误以为本次呼叫新发成功。
- [spec 过滤后旧记录缺 spec 字段导致不可见] → 数据检查确认 escalation/disposition 记录均带 `spec` 字段；过滤条件用 `==` 严格匹配，`signal` 类内部记录本就不该出现在弹窗。

## Migration Plan

纯增量功能，无数据迁移。回滚 = 还原 app.js / server.py / data.py / watcher.py 四处改动；`admin_alerts.json` 结构零变更，无兼容包袱。

## Open Questions

（无 —— 需求口径已与用户确认：呼叫成功自动弹窗、spec 过滤、SSE 实时更新复用 timeline 机制。）

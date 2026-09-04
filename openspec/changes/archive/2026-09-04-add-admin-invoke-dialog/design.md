# add-admin-invoke-dialog — Design (v2)

## Context

- 手动呼叫链路：POST `/api/spec-admin-invoke` → 写 `.fenix/admin_invoke_request.json` → daemon/admin_monitor 巡检拾取 → `agent_runner.run_administrator(signal)`。
- **Admin run 事实**（v2 关键依据）：`run_administrator` 生成 `run_id = "admin-<spec>-<ts>"`，**唤起前先落 pending disposition**（含 `admin_run_id`）到 `admin_alerts.json`；Administrator 直接在 main 树运行，过程事件写入 `.fenix/runs/admin-<spec>-<ts>.jsonl`。
- **现有 run 实时链路（复用主体）**：run 弹窗 `modalRunId` + `GET /api/runs/<run_id>` 事件拉取 + `registerWatch/unregisterWatch`（POST/DELETE `/api/runs/<run_id>/watch?cid=`）+ SSE `run_events` 增量推送 + 事件时间轴渲染（用户所指「timeline 中查看各 Agent 消息的实现」）。watcher 本就监听 `runs/*.jsonl`。
- **首版已落地、v2 沿用为支撑件**：`get_admin_activities(spec=)` 服务端过滤 + 端点透传（解析 `admin_run_id` 的途径）；watcher 监听 `admin_alerts.json` 并广播轻量事件 `{type: "admin_activities", project}`（等待态感知 run 启动的信号源）。
- 用户需求口径（v2）：呼叫成功（含 409）自动弹窗；弹窗看**处置过程输出**而非结果记录卡片；SSE 实时；可关闭、后台处置不受影响。

## Goals / Non-Goals

**Goals**

- 呼叫后立即有可见反馈：等待态 → 实时输出 → 最终状态，全程无手动刷新。
- 最大化复用既有 run 弹窗链路（数据拉取、watch、SSE 推送、时间轴渲染）。

**Non-Goals**

- 不改变 `/api/spec-admin-invoke` 呼叫信号机制与 `run_administrator` 的唤起流程。
- 不做弹窗内操作能力（标记已处理等），弹窗只读。
- 不重做运维记录视图（其定位仍是结果留痕视图）。

## Decisions

**D1 — 弹窗主体复用 run 弹窗的 run_events 链路，而非运维记录卡片。**
弹窗解析到 `admin_run_id` 后走与 run 弹窗完全相同的路径：拉取 run 事件、注册 watch、响应 `run_events` 增量推送、用时间轴渲染 Agent 消息。理由：这正是用户点名的「timeline 查看各 Agent 消息的实现」；处置过程天然就是 run jsonl 事件流，重造渲染毫无收益。备选「继续展示 disposition 卡片 + 结果」已被用户否决（只显示结果、过程不可见）。

**D2 — run 定位：`GET /api/admin-activities?project=&spec=` 解析 `admin_run_id`。**
弹窗打开时及等待态收到 `admin_activities` 广播后，重拉该端点，取该 SPEC 最新（优先 pending、其次最终）disposition 记录的 `admin_run_id`。理由：首版后端过滤直接复用，零新增后端工作；`run_administrator` 保证唤起前必落 pending（fix-admin-self-heal），`admin_alerts.json` 变更必触发 watcher 广播，事件驱动可靠。

**D3 — 等待态：轻量兜底轮询 + 事件驱动双通道。**
等待态期间除响应 `admin_activities` 广播外，以 5s 间隔兜底重拉解析端点（弹窗打开期间才轮询，解析成功即停）。理由：SSE 断线重连窗口期可能错过广播，轮询兜底避免等待态卡死；轮询范围仅限单个轻量端点，成本可忽略。

**D4 — 409 视为弹窗触发成功（沿用 v1）。**
409 即该 SPEC 已有处置进行中，正是最需要看到处置进度的场景；进入同一弹窗流程（解析既有 run）。弹窗顶部保留「已有处置进行中」提示行。

**D5 — 弹窗状态与清理沿用 run 弹窗模式。**
新增 `modalAdminSpec` 状态（与 `modalRunId` 同模式）：打开时记录 project/spec 并进入等待态；解析到 `admin_run_id` 后注册 watch 并渲染；SSE `run_events` 到达时仅当弹窗打开且 run 匹配才增量更新；关闭时 `unregisterWatch` 并清空状态。顶部状态行数据取自该 SPEC 最新 disposition 的 status 字段（处置中/已完成/已中断），随广播事件一并刷新。

## Risks / Trade-offs

- [SSE 断线窗口期错过 `admin_activities` 广播导致等待态滞留] → D3 的 5s 兜底轮询消除滞留；run 已启动后 `run_events` 断线由 EventSource 原生重连 + onopen 补拉兜底。
- [同 SPEC 连续两次呼叫产生多个 admin run] → 解析端点按时间倒序取最新 disposition，弹窗始终跟随最新 run；历史 run 可在运维记录视图回溯（不属本弹窗职责）。
- [`admin-<spec>-<ts>` run 被 `clean_old_runs` 清理] → 处置期间 run 文件受 `active_ids` 保护（agent_runner 现有机制）；弹窗拉取 404 时回退等待态并重解析。
- [409 弹窗改变原 toast 错误语义] → 弹窗顶部「已有处置进行中」提示行明示来源，避免误认为本次新发呼叫。

## Migration Plan

v1 已实现并推送（backend spec 过滤/watcher 监听沿用保留）。v2 改动集中在前端弹窗（app.js）：记录卡片渲染替换为 run 事件时间轴 + 等待态/切换逻辑。回滚 = 还原 app.js 对应改动。

## Open Questions

（无 —— v2 口径已与用户确认：弹窗展示处置过程实时输出，复用 timeline 查看 Agent 消息的实现。）

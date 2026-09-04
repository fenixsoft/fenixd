## Why

SPEC 右键菜单「呼叫 Admin 介入」目前呼叫成功后仅弹一条 toast，用户无法直观看到 Administrator 是否已在处置、处置进行到哪一步。用户明确要求：弹窗要展示 Admin **处置过程中的实时输出**（Agent 消息流），而不是仅显示结果的处置记录卡片——运维记录视图只留痕结果，处置「黑盒进行中」的过程对呼叫方不可见。

> 2026-08-29 需求变更（v2）：首版 SPEC 将弹窗内容定为复用运维记录视图的处置记录卡片，已按首版实现并推送。用户反馈该视图只显示结果，要求改为展示处置过程输出，本版据此重写弹窗内容需求。

## What Changes

- 点击「呼叫 Admin 介入」菜单项，呼叫成功（或 409 已在处置中）后自动弹出一个**处置过程弹窗**，不再只显示 toast。
- 弹窗主体展示该 SPEC 对应 Administrator run 的**实时输出**：复用运行时间轴查看各 Agent 消息的现有链路（run watch + `run_events` SSE 增量推送），渲染 Agent 消息事件时间轴。
- Administrator 尚未启动时显示等待态；run 启动（pending disposition 落盘、`admin_alerts.json` 变更广播）后自动切换为实时输出视图。
- 弹窗顶部显示当前处置状态（处置中/已完成/已中断）。
- 用户可随时关闭弹窗；关闭取消 run watch，不影响 Admin 后台处置。
- Dashboard 后端（首版已落地，本版沿用为支撑件）：`GET /api/admin-activities` 的 `spec` 过滤参数用于解析该 SPEC 的 `admin_run_id`；FileWatcher 对 `.fenix/admin_alerts.json` 的监听与轻量广播事件用于等待态感知 run 启动。

## Capabilities

### New Capabilities

- `admin-invoke-record-dialog`: 呼叫 Admin 后的处置过程弹窗能力，覆盖呼叫触发弹窗、等待态、定位 Admin run 并实时展示处置过程输出（`run_events` 增量推送）、可关闭且后台处置不受影响。

### Modified Capabilities

（无 —— 呼叫信号写入机制、运维记录视图、run 弹窗等既有能力均无 spec 级修改；本能力仅新建弹窗并复用既有 run watch/SSE 链路。）

## Impact

- `.fenix/core/dashboard/static/app.js`：`_ctxAdminInvoke` 后置行为（首版已改，本版沿用）；处置记录弹窗改造为处置过程弹窗——解析 `admin_run_id`、复用 run 弹窗的事件时间轴渲染与 watch 注册、等待态与自动切换、关闭清理。
- `.fenix/core/dashboard/server.py` / `data.py`：首版已实现的 `spec` 过滤参数沿用，无新增改动（除必要时的小修）。
- `.fenix/core/dashboard/watcher.py`：首版已实现的 `admin_alerts.json` 监听与轻量广播沿用，作为等待态发现 run 启动的信号源。
- 无数据库/外部依赖变更；`admin_alerts.json` 与 run jsonl 结构不变，纯读取侧组装。

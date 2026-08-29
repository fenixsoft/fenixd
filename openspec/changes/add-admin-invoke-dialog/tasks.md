# add-admin-invoke-dialog — Tasks (v2)

> v2 需求变更：弹窗内容从「处置记录卡片（复用运维记录视图）」改为「Administrator 处置过程实时输出（复用 run 事件时间轴链路）」。§1/§2 首版已实现且 v2 沿用为支撑件，无需重做；本次改动集中在 §3（前端弹窗重做）与 §4 验证。

## 1. 后端数据与端点（首版已完成，v2 沿用）

- [x] 1.1 `data.py`：`get_admin_activities(project_root, spec=None)` 可选 spec 过滤（归并/置顶后按 `rec.get("spec") == spec` 过滤）——v2 用作解析 `admin_run_id` 的途径
- [x] 1.2 `server.py`：`_api_admin_activities` 透传可选 `spec` 查询参数

## 2. SSE 推送链路（首版已完成，v2 沿用）

- [x] 2.1 `watcher.py`：监听 `.fenix/admin_alerts.json` mtime 变更
- [x] 2.2 `watcher.py`：广播轻量事件 `{"project": <name>, "type": "admin_activities"}`——v2 用作等待态感知 run 启动的信号源

## 3. 前端弹窗重做（v2 核心）

- [x] 3.1 `app.js`：处置记录弹窗改造为处置过程弹窗——打开时记录 `modalAdminSpec`，立即重拉 `GET /api/admin-activities?project=&spec=` 解析该 SPEC 最新 disposition 的 `admin_run_id`（优先 pending、其次最终，按时间倒序）
- [x] 3.2 `app.js`：等待态——未解析到 `admin_run_id` 时显示「等待 Administrator 开始处置」；期间响应 `admin_activities` 广播事件重拉解析，另加 5s 兜底轮询（仅弹窗打开期间，解析成功即停）
- [x] 3.3 `app.js`：解析到 `admin_run_id` 后复用 run 弹窗链路——拉取 run 事件、`registerWatch(run_id)`、用现有时间轴渲染展示 Agent 消息；顶部状态行显示处置状态（处置中/已完成/已中断，随 `admin_activities` 广播刷新）；409 来源时顶部附「已有处置进行中」提示行
- [x] 3.4 `app.js`：`run_events` SSE 增量推送在弹窗打开且 run 匹配时更新时间轴（与 run 弹窗同处理）；run 拉取 404（文件被清理）时回退等待态并重解析
- [x] 3.5 `app.js`：关闭弹窗时 `unregisterWatch`、停止兜底轮询、清空 `modalAdminSpec`；关闭后后台处置不受影响

## 4. 验证

- [ ] 4.1 场景验证：呼叫成功弹窗（等待态）、409 弹窗（提示行 + 定位既有 run）、失败不弹窗
- [ ] 4.2 实时链路验证：等待态期间模拟 pending disposition 写入 `admin_alerts.json` → 弹窗自动切换实时输出；run jsonl 追加新事件 → 时间轴无手动刷新即出现新 Agent 消息（真实服务验证，mock 会斩断 SSE 链路）
- [ ] 4.3 关闭与收尾验证：关闭弹窗后 run 继续写事件不报错、watch 已注销；处置完成后弹窗重开可见完整过程与最终状态
- [ ] 4.4 回归验证：运维记录视图与 run 弹窗（modalRunId）行为不受影响；`/api/admin-activities` 无 spec 参数时行为不变

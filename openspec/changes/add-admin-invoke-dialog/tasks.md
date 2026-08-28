# add-admin-invoke-dialog — Tasks

## 1. 后端数据与端点

- [ ] 1.1 `data.py`：`get_admin_activities(project_root, spec=None)` 增加可选 spec 参数，在归并/置顶逻辑完成后按 `rec.get("spec") == spec` 过滤
- [ ] 1.2 `server.py`：`_api_admin_activities` 读取可选 `spec` 查询参数并透传给 `get_admin_activities`；无 spec 时行为不变

## 2. SSE 推送链路

- [ ] 2.1 `watcher.py`：`_iter_project_files` 增加 `.fenix/admin_alerts.json` 监听（新 kind），`scan_once` 检测 mtime 变化后调用新 handler
- [ ] 2.2 `watcher.py`：新增 `_handle_admin_change`，广播轻量事件 `{"project": <name>, "type": "admin_activities"}`（不带数据）

## 3. 前端弹窗

- [ ] 3.1 `app.js`：`_ctxAdminInvoke` 改造——2xx 与 409 均进入打开弹窗分支，其他错误仅 toast；409 时弹窗顶部显示「已有处置进行中」提示行
- [ ] 3.2 `app.js`：新增处置记录弹窗（复用现有 modal 框架），打开时记录 `modalAdminSpec` 状态并拉取 `GET /api/admin-activities?project=<name>&spec=<name>` 渲染
- [ ] 3.3 `app.js`：弹窗渲染复用 `activityCard`/状态标签样式，空数据时显示「该 SPEC 暂无处置记录」空态；支持关闭，关闭时清空弹窗状态
- [ ] 3.4 `app.js`：`handleSSEEvent` 增加 `admin_activities` 类型处理——仅当弹窗打开且 project 匹配时重拉该 SPEC 记录并重渲染；SSE onopen 重连后弹窗打开状态下补拉一次

## 4. 验证

- [ ] 4.1 手动/脚本验证：呼叫成功自动弹窗、409 弹窗、失败不弹窗三个场景（参照 verify 快照语义，mock 斩断 SSE 链路的场景需真实服务验证实时刷新）
- [ ] 4.2 验证 SSE 实时更新：弹窗打开期间模拟 disposition 记录写入 `admin_alerts.json`，确认弹窗无手动刷新即更新；关闭弹窗后写入不报错
- [ ] 4.3 回归验证运维记录视图（`view === 'activities'`）与 spec 过滤参数缺省时 `/api/admin-activities` 行为不变

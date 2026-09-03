## 1. 后端基础设施（数据层 + 启停辅助）

- [x] 1.1 `Registry` 支持 `ignored` 忽略列表：`dashboard.yaml` 顶层新增 `ignored: []`；`load()`/`save()` 透传；`discover()` 在合并显式与扫描结果后按规范化路径过滤 `ignored` 命中项
- [x] 1.2 `Registry.add_ignored(path)`：把规范化路径追加进 `ignored` 并写回（去重）；`Registry.is_ignored(path)` 供查询
- [x] 1.3 `core/fenix_session.py` 或新增辅助模块实现 `start_daemon(root)`：校验 `.fenix`/`STATE.md`，以 `tmux new-session -d -s <session> "cd <root> && python3 .fenix/fenixd.py 2>&1 | tee .fenix/logs/stdout.log"` 拉起，等待 `is_running` 命中，幂等（已运行返回 already）
- [x] 1.4 实现 `stop_daemon(root)`：先 `tmux send-keys -t <session> C-c` 优雅关闭，轮询 `is_running` 至多 5s，超时 `tmux kill-session` 强制终止，幂等（未运行不报错）
- [x] 1.5 `data.spec_summary` 新增 `total_duration`：该 spec 全部 run（`get_runs(project_root, spec_name)`）的 `duration_seconds` 求和，无 run 为 0
- [x] 1.6 `agent_runner._read_disposition` 将 `actions_taken`/`summary` 列表 join 分隔符从 `；` 改为 `\n`（每条独立一行）

## 2. 服务端管理 API

- [x] 2.1 `server.py` `_handle_api_post` 新增 `POST /api/projects/<name>/start`、`POST /api/projects/<name>/stop`：按 `project_by_name` 解析项目，`exists=False` 或未知返回 400；调用 `start_daemon`/`stop_daemon`，成功返回 `{ok, session?, error?}`
- [x] 2.2 `_handle_api_delete` 新增 `DELETE /api/projects/<name>`：软删除 = `stop_daemon` + `Registry.add_ignored(path)`，返回 `{ok, error?}`
- [x] 2.3 三个管理端点成功后经 SSE Hub 广播 `{type:"refresh"}`；tmux/环境异常时返回 `{ok:false, error}` 且 HTTP 非 500

## 3. 前端：概览项目生命周期控制

- [x] 3.1 概览项目卡片新增「启动 / 停止」按钮，按 `daemon` 状态禁用对应项，点击调用对应 API 后刷新概览
- [x] 3.2 项目卡片新增「删除」操作：二次确认对话框（文案说明保留文件、可编辑配置恢复），确认后调用 `DELETE` 并刷新
- [x] 3.3 操作失败（HTTP 非 2xx）时页面显示可读错误提示，不影响其它项目卡片

## 4. 前端：运维记录页签 + 处置记录换行

- [x] 4.1 `renderActivities` 跨项目视图改为页签栏（「全部」+ 各项目名），页签切换为模块级状态并在刷新/SSE 重绘后保持；单项目路由 `activities/<project>` 不变
- [x] 4.2 `style.css` 为 `.activity-action`、`.activity-reco`、`.activity-fallback` 增加 `white-space: pre-wrap; word-break: break-word`

## 5. 前端：项目表格排序 / 耗时列 / fix 树

- [x] 5.1 表头 `<th>` 支持点击排序（升序/降序/取消轮换），模块级 `specSort` 状态在刷新后保持，表头显示方向箭头，缺失值排末尾，状态列按生命周期顺序排序
- [x] 5.2 SPEC 表格新增「耗时」列：渲染 `total_duration`（`fmtDuration`，0 显示「—」），参与排序
- [x] 5.3 fix-* 树状分组：递归去前导 `fix-` 定位父规格，子行缩进 + 🔧 标记，排序以根为粒度整体排序不拆散树，孤立 fix 归入「无父级」分组

## 6. 前端：spec 详情页页签

- [x] 6.1 `renderSpec` 将运行时间轴/场景结果/Bug 列表/失败截图四个区块改为独立页签（模块级 `specTab`，默认「运行时间轴」，刷新后保持，空数据页签显示占位）
- [x] 6.2 验证结论/验证进度/任务清单常驻顶部不被页签收纳；切换到「运行时间轴」页签时在 DOM 就位后触发 `mountTimeline` 挂载
- [x] 6.3 新增页签栏样式（`style.css`），与既有卡片/按钮视觉风格一致

## 7. 验证与回归

- [x] 7.1 后端单测：Registry `ignored` 过滤、`total_duration` 求和、管理 API 端点（mock tmux）返回与错误路径
- [x] 7.2 浏览器冒烟：概览启停/删除、运维记录页签与换行、表格排序/耗时/fix 树、spec 详情页签切换，回归既有五视图（概览/项目/详情/配置/运维记录）与 SSE 自动刷新

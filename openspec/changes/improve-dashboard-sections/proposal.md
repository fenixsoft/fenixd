## Why

Fenix Dashboard 各截面功能已能覆盖监控与排障，但交互与信息密度不足：跨项目概览无法管理项目生命周期（启停 daemon、移除监控）；运维记录平铺过长且处置记录丢失换行；项目概览表格不支持排序、缺少耗时指标、fix-* 规格与其父规格平铺割裂；spec 详情页四个长区块（时间轴/场景结果/Bug/截图）平铺导致页面过长。本次统一改进 Dashboard 各截面，让监控、运维、排障三个场景都更高效。

## What Changes

- **跨项目概览**：项目卡片新增「启动 / 停止」fenixd daemon 按钮（复用 tmux session 管理），以及「删除项目」操作——软删除：停止 daemon + 写入忽略列表，该项目不再被自动发现，项目文件与数据保留，可从配置恢复。
- **运维记录**：跨项目视图改为按项目分页签展示（含「全部」页签），不再平铺；处置记录（summary / action_taken / recommended_action）多行内容保留换行展示。
- **项目概览**：
  - 表格表头支持点击排序（状态/名称/优先级/创建时间/任务进度/验证/耗时/错误）。
  - 新增「耗时」列：该 spec 全部运行（impl/verify/planner/test 等 run）时长之和。
  - fix-* 规格以树状结构缩进显示在对应父规格下（去掉前导 `fix-` 递归定位父规格）。
- **spec 详情页**：验证结论/验证进度/任务清单常驻顶部；运行时间轴、场景级测试结果、Bug 列表、失败截图四个长区块改为独立页签。
- **BREAKING**：无。运维记录单项目路由 `activities/<project>` 与顶部项目下拉行为保持不变。

## Capabilities

### New Capabilities

- `project-lifecycle-control`: 跨项目概览中启动/停止指定项目的 fenixd daemon，以及软删除项目（停止 daemon + 写入忽略列表，不再自动发现；文件保留可恢复）。
- `activity-records-tabs`: 运维记录跨项目视图按项目分页签展示；处置记录多行内容保留换行。
- `spec-table-improvements`: 项目概览表格表头可点击排序、新增「耗时」列（运行时长之和）、fix-* 规格以树状缩进挂载到父规格下。
- `spec-detail-tabs`: spec 详情页四个长区块（运行时间轴/场景结果/Bug 列表/失败截图）改为独立页签，顶部常驻验证结论/验证进度/任务清单。

### Modified Capabilities

无（本框架各 change 自带 specs，无全局能力规格文件）。

## Impact

- **后端 API**（`core/dashboard/server.py`）：
  - 新增 `POST /api/projects/<name>/start`、`POST /api/projects/<name>/stop`（启停项目 daemon）。
  - 新增 `DELETE /api/projects/<name>`（软删除：停止 daemon + 忽略列表）。
- **项目发现**（`core/dashboard/registry.py`）：`dashboard.yaml` 新增 `ignored` 列表；`discover()` 跳过被忽略路径（含自动扫描命中）。
- **daemon 启停**（`core/fenix_session.py` 或新增辅助函数）：`start_daemon(root)` 按 `fenix-setup` 同等命令经 tmux 拉起；`stop_daemon(root)` 发 SIGTERM 优雅关闭后 kill session。
- **数据聚合**（`core/dashboard/data.py`）：`spec_summary` 增加 `total_duration`（该 spec 全部 run 的 `duration_seconds` 求和）。
- **前端**（`core/dashboard/static/app.js`、`style.css`）：概览卡片操作按钮、运维记录项目页签、表格排序/耗时列/fix 树、spec 详情页签结构。
- 不涉及 daemon 主进程（`fenixd.py` / `pm_engine`）行为变更。

# 能力：key-path-stale-preflight（关键路径执行前陈旧代码预检）

## ADDED Requirements

### Requirement: 陈旧旗标共享查询

daemon 侧已有的代码陈旧判定（进程启动 mtime 基线 vs 磁盘当前，每 30 秒重算的 `_code_stale` 旗标，fenixd.py:1359）SHALL 以模块级只读查询的形式暴露给 core/ 各关键路径模块。

- 注册表 SHALL 落在 core/ 侧（新模块 `core/code_stale_flag.py`；daemon 启动初始化与每 30 秒检测点写入，core 关键路径模块读取）；MUST NOT 出现 core 反向 import daemon（既有成文约定见 core/git_base_branch.py:19）；
- 注册表 MUST 线程安全：daemon 检测线程写、车道线程读，且查询本身不产生任何 IO；
- 未注册（单元测试、非 daemon 语境、冷启动窗口）时查询 SHALL fail-open 返回「不陈旧」。

#### Scenario: 注册后查询返回当前陈旧态

- **WHEN** daemon 已注册旗标回调且 `_code_stale` 为真
- **THEN** 任意 core 模块查询 `is_stale()` 返回真
- **AND** `_code_stale` 翻假后查询返回假

#### Scenario: 未注册 fail-open

- **WHEN** 注册表从未被 daemon 注册（pytest、独立脚本、冷启动窗口）
- **THEN** 查询返回假（不陈旧），不抛异常、不产生 IO

### Requirement: 关键路径执行前预检

以下三个关键路径入口 SHALL 在动作执行前查询陈旧旗标，且仅在查询结果为陈旧时执行预检动作；查询为不陈旧时行为与现状完全一致：

- a) verification-report 收尾提交：插桩位于 core/pm_engine/engine.py 收尾步内、调用 `core/verify_report.py::_commit_verification_report` 的调用点之前（engine.py:3014-3016 语境）；core/verify_report.py 本体不改、不在交付清单，其文件内其余三处 `_commit_verification_report` 调用点（verify_report.py:1172/1190/1233）不在本 SPEC 范围；
- b) 知识蒸馏批次派发：插桩收敛在 `core/knowledge.py::DistillManager.dispatch` 单汇聚点——单条/批量入口（dispatch_distill / dispatch_distill_batch）均经 `_dispatch_via_mgr`（core/knowledge.py:1388）到达该单点，MUST NOT 在 dispatch_distill 与 DistillManager.dispatch 两处重复插桩（单条路径会双告警）；
- c) admin 车道处置 choice 执行：core/admin_monitor.py 的 `_apply_choice_execution` 调 `execute_adjudication_choice`（core/dashboard/data/admin_actions.py:3545）之前。

查询结果为陈旧时 SHALL 按序：记一条 WARNING（含陈旧状态与已请求重启的事实）→ 确保 `.fenix/restart_request` 存在（已存在则不重复写）→ 当前关键路径动作照常完成，不被预检阻塞或中断。

#### Scenario: 陈旧时预检并照常执行

- **WHEN** 旗标为真且收尾提交、蒸馏派发、choice 执行任一开始
- **THEN** 该路径产生一条 WARNING 日志且确保 .fenix/restart_request 存在
- **AND** 动作本身返回值与产物和不预检时一致

#### Scenario: 新鲜或未注册时零新增副作用

- **WHEN** 旗标为假或注册表未注册
- **THEN** 关键路径行为与现状一致：无新增日志、无新文件写入

#### Scenario: 蒸馏单条与批量路径各只告警一次

- **WHEN** 旗标为真且 dispatch_distill（单条）或 dispatch_distill_batch（批量）派发
- **THEN** 预检在 DistillManager.dispatch 单汇聚点各恰好产生一条 WARNING、一次防重确保

### Requirement: restart_request 防重与路径锚点

- restart_request 已存在时 SHALL NOT 重复写入或刷写其 mtime（与既有自愈「restart_request 已在，重启在途，不重复写入」语义一致）；
- 路径 SHALL 解析为 daemon 自身仓库的 `.fenix/restart_request`（与 supervisor 的 `RESTART_REQUEST`（.fenix/bin/fenixd_supervisor.py:52）同一文件），MUST NOT 按 project_root 相对解析（治理第三方项目时 supervisor 只读 daemon 侧该文件）；
- 预检本身 SHALL NOT 产生其他副作用：不写额外状态、不改变关键路径动作的返回值与产物。

#### Scenario: 已存在不刷写

- **WHEN** .fenix/restart_request 已存在且关键路径在陈旧态执行
- **THEN** 不重复写文件、其 mtime 不变，动作照常完成

#### Scenario: 路径锚点为 daemon 侧 .fenix

- **WHEN** 关键路径动作的 project_root 指向非 daemon 仓库目录且旗标为真
- **THEN** restart_request 仍写 daemon 仓库的 .fenix/restart_request，而非 project_root 下的 .fenix

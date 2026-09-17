# Tasks: refactor-giant-classes

## Deliverables

```yaml
- path: core/worktree_manager/__init__.py
  kind: new
- path: core/worktree_manager/lifecycle.py
  kind: new
- path: core/worktree_manager/legacy_registry.py
  kind: new
- path: core/worktree_manager/locks.py
  kind: new
- path: core/worktree_manager/mergeback.py
  kind: new
- path: core/worktree_manager/dist_conflicts.py
  kind: new
- path: core/worktree_manager/stash_guard.py
  kind: new
- path: core/worktree_manager/stale_sweep.py
  kind: new
- path: core/worktree_manager/queries.py
  kind: new
- path: core/worktree_manager/repair_site.py
  kind: new
- path: core/worktree_manager/types.py
  kind: new
- path: core/worktree_manager.py
  kind: delete
- path: core/pm_engine/dispatch/__init__.py
  kind: new
- path: core/pm_engine/dispatch/queue.py
  kind: new
- path: core/pm_engine/dispatch/backoff.py
  kind: new
- path: core/pm_engine/dispatch/adjudication.py
  kind: new
- path: core/pm_engine/dispatch/rollback.py
  kind: new
- path: core/pm_engine/dispatch/fast_track.py
  kind: new
- path: core/pm_engine/dispatch/repair_lane.py
  kind: new
- path: core/pm_engine/dispatch.py
  kind: delete
- path: core/dashboard/routes/__init__.py
  kind: new
- path: core/dashboard/routes/base.py
  kind: new
- path: core/dashboard/routes/project_routes.py
  kind: new
- path: core/dashboard/routes/spec_routes.py
  kind: new
- path: core/dashboard/routes/run_routes.py
  kind: new
- path: core/dashboard/routes/settings_routes.py
  kind: new
- path: core/dashboard/routes/alert_routes.py
  kind: new
- path: core/dashboard/routes/evolution_routes.py
  kind: new
- path: core/dashboard/routes/help_routes.py
  kind: new
- path: core/dashboard/routes/sse_routes.py
  kind: new
- path: core/dashboard/routes/static_routes.py
  kind: new
- path: core/dashboard/sse.py
  kind: new
- path: core/dashboard/http_server.py
  kind: new
- path: core/dashboard/server.py
  kind: modify
- path: bin/gen-route-map.py
  kind: modify
- path: tests/test_characterization_giant_classes.py
  kind: new
- path: spec/changes/refactor-giant-classes/contract-inventory.md
  kind: new
- path: spec/changes/refactor-giant-classes/giant-classes-findings.md
  kind: new
```

> `core/dashboard/server.py` 的 `kind: modify` 保留进程/生命周期模块函数（`serve` 等）与门面组装；`bin/gen-route-map.py` 的 `kind: modify` 仅限 design D4 的路由扫描源同步。

## 1. 阶段 0：测试基线加固

- [x] 1.1 静态清点：把 `WorktreeManager`（**83** 方法）/ `Dispatcher`（**56**）/ `DashboardHandler`（**80** + 伴生类 `SSEConnection`/`SSEHub`/`DashboardHTTPServer` + 10 模块函数）全部方法逐名落位到 design D1 三张分组表，落盘 `contract-inventory.md`，**不留未归属项**。清点须以 AST/静态解析结果计数并与三张表的条目数逐类比对（83 / 56 / 80），数量不等即视为未归属项存在，MUST 先补齐 design 分组表再进阶段 1
- [x] 1.2 补 characterization tests（`tests/test_characterization_giant_classes.py`）：重点覆盖盲区——worktree G5（`_run_dist_build`/`_rebuild_dist_after_merge`）/G6（`_purge_ignored_brought_in`/`_resolve_ignored_modify_delete_conflicts`）/G4（`_detect_wip_overlap`）；dispatch B 组（`_on_instant_fail_recovery`/`_on_transient_recovery`）、adjudication 组
- [x] 1.3 建立疑点清单（`giant-classes-findings.md`），只记录不修
- [x] 1.4 运行 `bin/run_full_suite.py` 记录基线失败集合
- [x] 1.5 **patch 缝隙清点**（design D3）：逐项固定 worktree（2 处模块级 patch、类属性 `_rehearsal_*`、`_impl_branch_owned_by_spec`、8 常量、`MergeConflictInfo`）、dispatch（`time` 重绑、`_dispatch_backoffed`、2 常量）、server（4 类 monkeypatch、9 处 `start_daemon`/`stop_daemon` 字符串 patch、10 个被 import 名）的当前语义基线
- [x] 1.6 **隐性消费方清点**（design D4）：记录 `bin/gen-route-map.py::scan_server_routes` 的扫描源与 `tests/test_planner_route_map.py` 的消费口径
- [x] 1.7 **私有回引清点**（design D5）：落盘 `Dispatcher` 的 52 个 `self._pm._X` 目标（130 处）清单，标注高频 5 个

## 2. 阶段 1：worktree_manager → 子包

- [x] 2.1 按 design D2 把 `core/worktree_manager.py` 改名为 `core/worktree_manager/_legacy.py` 并建包，门面 re-export 全部公开名（8 常量、`MergeConflictInfo`、`_is_claude_process`、`_is_build_artifact_path`），本 commit 上既有 import 全可用
- [x] 2.2 摘出 G3（`locks.py`）与 G8（`queries.py`）——纯工具/只读层，低耦合
- [x] 2.3 摘出 G2（`legacy_registry.py`）与 G9（`repair_site.py`）
- [x] 2.4 摘出 G1（`lifecycle.py`）
- [x] 2.5 摘出 G5（`dist_conflicts.py`）与 G6（`stash_guard.py`）
- [x] 2.6 摘出 G4（`mergeback.py`）——含 208 行 `_merge_back_from_branch_locked` 原样搬移（方法体不改）
- [x] 2.7 摘出 G7（`stale_sweep.py`）与 `types.py`；删除 `_legacy.py`
- [x] 2.8 类级状态核对：`_rehearsal_probe_done`/`_rehearsal_supported` 仍挂 `WorktreeManager` 类命名空间；`_impl_branch_owned_by_spec` staticmethod 类直调可用
- [x] 2.9 运行 characterization tests 与全量回归，比对基线

## 3. 阶段 2：dispatch → 子包

- [x] 3.1 按 design D2 改名为 `core/pm_engine/dispatch/_legacy.py` 建包，门面 re-export `Dispatcher`/`DEFAULT_DISPATCH_BACKOFF_SCHEDULE`/`MAX_REPAIR_ROUNDS_PER_FAILURE`
- [x] 3.2 摘出 R（`rollback.py`，含 staticmethod `_honest_exit_gap`/`_dispatch_backoffed`）与 B（`backoff.py`）
- [x] 3.3 摘出 V（`adjudication.py`）——组内自洽度最高
- [x] 3.4 摘出 F（`fast_track.py`）
- [x] 3.5 摘出 P（`repair_lane.py`）
- [x] 3.6 摘出 Q（`queue.py`，含 742 行 `_run_agent_worker` 原样搬移）；`time` 引用经 `core.pm_engine.dispatch` 命名空间；`_dispatch_backoffed` 留类命名空间
- [x] 3.7 删除 `_legacy.py`；核对 engine.py 的 10 个队列状态 property 委托链不变
- [x] 3.8 按 design D5 消解 `_pm._X` 高频 5 个回引（其余保留清单待后续 spec）；运行回归比对基线

## 4. 阶段 3：dashboard server → routes/ 子包

- [x] 4.1 摘出伴生类：`core/dashboard/sse.py`（`SSEConnection`/`SSEHub`）、`core/dashboard/http_server.py`（`DashboardHTTPServer`）
- [x] 4.2 摘出 `routes/base.py`（H0 HTTP 底座，含 `_json`/`_error`/`_read_json_body` 共享方法）
- [x] 4.3 摘出资源子路由：`spec_routes.py`/`project_routes.py`/`settings_routes.py`/`alert_routes.py`/`run_routes.py`/`evolution_routes.py`/`help_routes.py`
- [x] 4.4 摘出 `sse_routes.py`（H9）与 `static_routes.py`（H10）
- [x] 4.5 把 `_handle_api`/`_handle_api_post`/`_handle_api_delete` 的 55 分支改造为**表驱动 + 按资源委派**（design D1）；参数化路径用 regex matcher；**保留 `endswith` 顺序陷阱**（project lifecycle 排在 describe 之后、`/api/projects/<name>` DELETE 之前）
- [x] 4.6 按 design D4 三条 MUST 同步 `bin/gen-route-map.py`：①`scan_server_routes` 扫描源（改为 `routes/` 子包或表驱动路由表）；②方法归属启发式（MUST NOT 再依赖回看 60 行判 POST/DELETE）；③自检 grep 源与 ① 同文件集合。确认 `tests/test_planner_route_map.py` 通过，并补一条**本仓覆盖回归断言**：对本仓重构前后各生成一次地图，条目数不得减少
- [x] 4.7 门面 re-export 校验：`serve`/`STATIC_DIR`/`DashboardHTTPServer`/`find_free_port`/`SSEHub`/`HELP_DOC_NAME_RE`/`_bind_parent_lifecycle`/`_claude_watchdog_loop`/`_proc_starttime`/`_start_claude_watchdog` 全部可用；`start_daemon`/`stop_daemon` 字符串 patch 语义保持
- [x] 4.8 端点集合核对：枚举重构前后 (path, method) 集合，确认完全相等；运行回归比对基线

## 5. 阶段 4：全量回归与收尾

- [x] 5.1 运行 `bin/run_full_suite.py` 与基线比对，确认不新增失败
- [x] 5.2 逐项运行 design D3 清单对应的 patch 缝隙测试文件，确认语义保持
- [x] 5.3 循环依赖检查：确认未引入新静态依赖环（design D6）
- [x] 5.4 汇报疑点清单最终态（`giant-classes-findings.md`）
- [x] 5.5 逐项勾选本 tasks.md 全部已完成任务

## 验证修复（原地打回第 1 轮）

### 上轮实现结论（自动携带，来自上一轮 implementer 收工结论）

三个巨型类（WorktreeManager 83 方法 / Dispatcher 56 / DashboardHandler 80+伴生类）全部按 design D1 分组表拆为子包/mixin：worktree_manager 9 组、dispatch 6 组、dashboard routes 10 组+伴生类独立；4.5 表驱动路由分派（GET 20/POST 33/DELETE 2，55 分支零变化）；4.6 gen-route-map 三条 MUST 同步+本仓覆盖回归断言；阶段4收尾——4.8 端点集合核对完全相等、5.1 有界全量回归 classification=存量（6 项失败⊆基线，无引入）、5.2 patch 缝隙专项全绿、5.3 无新静态依赖环、5.4 疑点清单最终态落盘。期间修复 routes 子模块遗漏 import（yaml/AGENT_PROMPT_FILES/project_agents_dir）与 verify_yaml_template __file__ 路径漂移。

上轮登记的 findings：
- deliverable-dispute: tests/test_giant_classes_contract.py — 应归 reference/移除——本 SPEC 的契约与 characterization 覆盖已由 tests/test_characterization_giant_classes.py + tests/test_planner_route_map.py 承载，无 test_giant_classes_contract.py 交付需求

- [x] 先复核失败有效性：逐条核对 `spec/changes/refactor-giant-classes/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码
- [x] 修复后重跑验证确认通过

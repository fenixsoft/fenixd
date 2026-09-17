# Design: refactor-giant-classes

## Context

前三条重构解决了三个巨型**文件**，但三个巨型**类**从未被覆盖，且均为全仓改动最频繁的文件：

| 文件 | 行数 | 类 | 方法数 | 模块级名 |
|---|---|---|---|---|
| `core/worktree_manager.py` | 4180 | `WorktreeManager`（83）+ `MergeConflictInfo`（4） | 87 | 8 常量 + `_is_claude_process` 别名 + `_is_build_artifact_path` |
| `core/pm_engine/dispatch.py` | 3856 | `Dispatcher` | 56 | 2 常量 |
| `core/dashboard/server.py` | 2843 | `DashboardHandler`（80）+ `SSEConnection`（2）/`SSEHub`（7）/`DashboardHTTPServer`（5） | 94 | 9 常量 + 10 模块函数 |

**循环依赖实测：三个文件均无反向 import，零环。** 但拆分时须防引入新环（见 D6）。

**测试规模**：三文件直接相关测试约 32,500 行（worktree 19 文件 10,495 行 / dispatch 21 文件 9,800 行 / server 22 文件 12,200 行）。

## Goals / Non-Goals

**Goals:**

- 三个巨型类按职责拆为子包 / 子模块，宿主类保留为薄门面。
- 既有 import 路径、字符串路径 patch 语义、类级状态、构造签名全部保持。
- 先补 characterization tests，再搬移。
- HTTP 端点集合与响应语义零变化。

**Non-Goals:**

- 不拆分 `Dispatcher._run_agent_worker`（742 行枢纽）与 `WorktreeManager._merge_back_from_branch_locked`（208 行）的方法体——**内部拆分风险高，属 `refactor-long-functions`/后续 spec 范畴**；本变更只做「类 → 子包」的模块级拆分，方法体原样搬移。
- 不修 bug（只记疑点清单）。
- 不改变任何语义、阈值、路由。

## Decisions

### D1：分组表即交付契约

三张分组表 MUST 覆盖全部方法，不留未归属项。

**A. `WorktreeManager`（→ `core/worktree_manager/` 子包，9 组）**

| 组 | 子模块 | 方法清单（83 全） |
|---|---|---|
| G1 创建/销毁生命周期 | `lifecycle.py` | `__init__`、`create`、`has_active_lock`、`_seed_spec`、`ensure_spec_committed`、`cleanup`、`_snapshot_dirty_worktree`、`cleanup_orphans`、`has_active_worktree`、`refresh_locks` |
| G2 遗产/复用注册表 | `legacy_registry.py` | `register_legacy`、`get_legacy`、`consume_legacy`、`has_legacy`、`keep_for_reuse`、`get_reuse_record`、`mark_reused`、`_take_reusable_worktree`、`_maybe_register_legacy_for_stale_lock`、`_guess_branch_from_worktree`、`_reclaim_expired_legacy` |
| G3 锁治理/进程判活 | `locks.py` | `_lock_spec_name`、`_register_spec_locks`、`_release_spec_locks`、`_lock_young`、`_spec_process_alive`、`_pgrep_spec_process`、`_latest_stream_mtime`、`_worktree_has_live_process`、`_kill_worktree_strays`、`_pid_alive` |
| G4 merge-back 主链 | `mergeback.py` | `get_branch_name`、`merge_back`、`merge_back_from_branch`、`_detect_wip_overlap`、`_merge_tree_supported`、`_rehearse_merge_from_branch`、`_parse_merge_tree_conflict_paths`、`_rehearsed_path_is_ignored_du`、`_merge_back_from_branch_locked`、`_backup_untracked_spec_files`、`_drop_backup`、`_restore_backup` |
| G5 构建产物冲突/dist 重建 | `dist_conflicts.py` | `_resolve_build_artifact_conflicts`、`_run_dist_build`、`_rebuild_dist_after_merge`、`_artifact_paths`、`_parse_merge_blockers`、`_list_unmerged_files`、`_collect_conflict_paths`、`_heal_unmerged_files` |
| G6 主树还原/autostash 治理 | `stash_guard.py` | `_list_dirty_tracked_files`、`ensure_clean_tree`、`restore_after_merge`、`_drop_superseded_stash_entry`、`reclaim_stale_autostash`、`_untrack_ignored_local_changes`、`_discard_identical_local_changes`、`_purge_ignored_brought_in`、`_resolve_ignored_modify_delete_conflicts` |
| G7 陈旧清扫 | `stale_sweep.py` | `cleanup_stale_worktrees`、`_read_state_entries`、`_branch_protected_by_state` |
| G8 查询/枚举（纯 git 只读） | `queries.py` | `_spec_from_worktree_name`、`_spec_from_branch`、`file_exists_on_branch`、`is_available`、`create_worktree_on_branch`、`find_worktree_path`、`find_worktree_by_spec`、`find_worktrees_by_spec`、`find_branches_by_spec`、`_wt_name_matches_spec`、`has_pending_merge`、`pending_merge_since`、`_impl_branch_owned_by_spec`、`branch_exists`、`branch_tip`、`find_implementer_worktree` |
| G9 repair/resume 站点认领 | `repair_site.py` | `repair_site_facts`、`resolve_repair_site`、`resolve_resume_site`、`claim_legacy_for_repair` |
| 数据类（原样保留） | `types.py` | `MergeConflictInfo`（`__init__`/`__iter__`/`__bool__`/`__repr__`） |
| 门面 | `__init__.py` | re-export `WorktreeManager`、`MergeConflictInfo`、8 常量、`_is_claude_process`、`_is_build_artifact_path` |

**B. `Dispatcher`（→ `core/pm_engine/dispatch/` 子包，6 组）**

| 组 | 子模块 | 方法清单（56 全） |
|---|---|---|
| Q 队列核心/worker | `queue.py` | `__init__`、`_get_spec_priority`、`_enqueue`、`_enqueue_front`、`_aging_bonus`、`_effective_priority`、`_process_queue`、`_run_agent_worker` |
| B 退避/瞬时恢复排程 | `backoff.py` | `_dispatch_backoff_schedule`、`_handle_dispatch_lock_conflict`、`_schedule_backoff_retry`、`_schedule_instant_fail_recovery`、`_schedule_instant_fail_recovery_locked`、`_on_instant_fail_recovery`、`_schedule_transient_recovery`、`_schedule_transient_recovery_locked`、`_on_transient_recovery` |
| V 交付物裁定/dispute | `adjudication.py` | `_record_impl_diagnosis`、`_build_dispute_judge_input`、`_dispute_spec_context`、`_read_dispute_verdicts`、`_commit_softened_declaration`、`_preclassify_missing`、`_adjudicate_deliverable_missing`、`_redispatch_for_missing`、`_redispatch_tasks_relint` |
| R 失败回滚/诊断上报 | `rollback.py` | `_rollback_failed_dispatch`、`_report_stash_pop_conflict`、`_honest_exit_gap`、`_dispatch_backoffed` |
| F fast-track 车道 | `fast_track.py` | `_fast_track_scale_precheck`、`_scale_precheck_config`、`_downgrade_fast_track_scale`、`_run_fast_track_worker`、`_run_fast_track_flow`、`_harvest_fast_track_worktree`、`_keep_fast_track_worktree`、`_release_fast_track_worktree`、`_reconcile_and_merge`、`_hard_check_fast_track`、`_fast_track_advance_to_verified`、`_rewrite_fast_track_to_full`、`_escalate_to_full_mode`、`_handle_fast_track_missing_result_merge`、`_handle_fast_track_failure`、`_handle_fast_track_zero_change`、`_handle_fast_track_deliverable_gate` |
| P merge-back 修复车道 | `repair_lane.py` | `_direct_rehearsed_to_repair`、`_should_enter_repair`、`_dispatch_repair_lane`、`_claim_repair_site`、`_run_repair_worker`、`_check_repair_commit_facts`、`_handle_remerge_failure`、`_fallback_after_repair`、`_repair_conflict_summary` |
| 门面 | `__init__.py` | re-export `Dispatcher`、`DEFAULT_DISPATCH_BACKOFF_SCHEDULE`、`MAX_REPAIR_ROUNDS_PER_FAILURE` |

**C. `DashboardHandler`（→ `core/dashboard/routes/` 子包 + 伴生类独立）**

| 组 | 子模块 | 方法清单 |
|---|---|---|
| H0 HTTP 底座（共享） | `base.py` | `do_GET/do_HEAD/do_POST/do_DELETE`、`log_message`、`_handle`、`_handle_inner`、`_read_json_body`、`_json`、`_error`、`_wants_gzip`、`_maybe_gzip` |
| H1 路由分派链 | `base.py`（`_handle_api`/`_handle_api_post`/`_handle_api_delete` 收敛为按资源委派） | `_handle_api`、`_handle_api_post`、`_handle_api_delete` |
| H2 project/overview | `project_routes.py` | `_api_projects`、`_api_overview`、`_project_query_or_error`、`_resolve_project_or_400`、`_api_project_lifecycle`、`_run_project_lifecycle_locked`、`_api_project_install_hosting`、`_api_project_delete`、`_api_project_describe`、`_project_from_query` |
| H3 spec 族 | `spec_routes.py` | `_api_specs`、`_api_spec_detail`、`_api_spec_doc`、`_api_spec_error_clear`、`_api_spec_priority`、`_api_spec_freeze`、`_api_spec_unfreeze`、`_api_spec_start_after`、`_api_spec_freeze_config`、`_api_spec_budget`、`_api_spec_archive`、`_api_spec_promote`、`_api_spec_task_reflow`、`_api_spec_re_review`、`_api_spec_approve_push`、`_api_spec_delete`、`_api_spec_admin_invoke` |
| H4 run/event | `run_routes.py` | `_api_run_cancel`、`_api_run`、`_api_run_watch`、`_api_events`、`_api_hooks_audit` |
| H5 配置/提示词/todo/verify-yaml | `settings_routes.py` | `_api_config_get`、`_api_config_post`、`_api_config_sync_from_user`、`_api_prompts_get`、`_read_project_extra`、`_api_prompts_post`、`_api_todo_get`、`_api_todo_post`、`_api_verify_yaml_get`、`_api_verify_yaml_post`、`_api_verify_yaml_template`、`_api_verify_yaml_autodraft_post` |
| H6 alerts | `alert_routes.py` | `_api_alerts`、`_api_admin_activities`、`_api_alert_handled`、`_api_alerts_clear` |
| H7 evolution | `evolution_routes.py` | `_evolution_state_machine`、`_api_evolution_items`、`_api_evolution_analysis`、`_api_evolution_draft`、`_api_evolution_accept`、`_api_evolution_reject`、`_api_evolution_delete`、`_api_evolution_clear_todo` |
| H8 help | `help_routes.py` | `_api_help_docs`、`_help_doc_title`、`_api_help_doc` |
| H9 SSE | `sse_routes.py` | `_handle_sse`、`_sse_client_gone`、`_sse_send` |
| H10 静态/截图 | `static_routes.py` | `_serve_static`、`_serve_screenshot`、`_send_file` |
| 伴生类 | `core/dashboard/sse.py`、`core/dashboard/http_server.py` | `SSEConnection`/`SSEHub`；`DashboardHTTPServer` |
| 模块函数 | 保留在 `server.py`（`serve` 等进程/生命周期函数与 `DashboardHandler` 组装） | `find_free_port`、`_project_lifecycle_lock`、`_find_dashboard_occupant`、`_is_dashboard_serve_cmd`、`_proc_starttime`、`_claude_watchdog_loop`、`_start_claude_watchdog`、`_bind_parent_lifecycle`、`serve`、`_is_process_alive` |

路由分派改造：`_handle_api`/`_handle_api_post`/`_handle_api_delete` 的 55 个分支（GET 20 = 18 精确 `path ==` + 2 `path.startswith`（`/api/specs/`、`/api/runs/`）；POST 33 = 27 精确 + 6 后缀（`/api/alerts/<id>/handled`、`/api/runs/<id>/watch`、`/start`、`/stop`、`/restart`、`/install-hosting`）；DELETE 2 = `/api/runs/<id>/watch` + `/api/projects/<name>`）MUST 改为**表驱动 + 按资源委派**——路由表 `(method, matcher, handler)`，参数化路径（`/api/alerts/<id>/handled`、`/api/runs/<id>/watch`）用 regex matcher。**MUST 保持 POST 链内的后缀陷阱顺序**：`_handle_api_post` 的 4 个裸 `endswith` 分支（`/start`、`/stop`、`/restart`、`/install-hosting`）是该方法**最后 4 个分支**，MUST 排在 `/api/project/describe` 之后（现状如此）；表驱动须按注册顺序匹配，MUST NOT 让裸后缀 matcher 前置到精确 matcher 之前。DELETE 的 `/api/projects/<name>` 在**独立方法** `_handle_api_delete` 中，与 POST 链无排序关系，跨方法顺序不作约束。

### D2：搬移顺序——先改名入包再逐组摘出

沿用 `refactor-verification-module` D8 先例：`x.py` → `x/_legacy.py`，建包，门面显式 re-export，再逐组摘出。MUST NOT 出现「旧模块与新包同时存在的中间态」（同名包会遮蔽同名模块）。

### D3：补丁缝隙保持（回归硬门）

| 文件 | 缝隙 | 保持策略 |
|---|---|---|
| worktree_manager | `patch("core.worktree_manager.subprocess.run")`、`patch("core.worktree_manager.time.time")` | 调用点经 `core.worktree_manager` 命名空间延迟解析 |
| worktree_manager | 类属性 `_rehearsal_probe_done`/`_rehearsal_supported`（测试直接赋值） | MUST 仍挂在 `WorktreeManager` 类命名空间 |
| worktree_manager | `WorktreeManager._impl_branch_owned_by_spec`（测试类直调 staticmethod） | MUST 留类命名空间 |
| worktree_manager | 8 常量 + `MergeConflictInfo` + `_is_claude_process` | 门面 MUST re-export 全部 |
| dispatch | `monkeypatch.setattr(_dispatch_mod, "time", _tick)` | 凡用 `time` 的组经 `core.pm_engine.dispatch` 命名空间解析 |
| dispatch | `Dispatcher._dispatch_backoffed`（`admin_monitor.py` 生产类直调 staticmethod） | MUST 留类命名空间 |
| dispatch | 2 常量 | 门面 re-export |
| server | `monkeypatch.setattr(server_mod, "HELP_DOCS_DIR"/"FRAMEWORK_ROOT"/"MAX_SSE_CONNECTIONS"/…)` | 调用点经 `core.dashboard.server` 命名空间延迟解析 |
| server | `patch("core.dashboard.server.start_daemon"/"stop_daemon")`（9 处字符串路径） | 调用点 MUST 经 `core.dashboard.server` 命名空间延迟解析 |
| server | `serve`/`STATIC_DIR`/`DashboardHTTPServer`/`find_free_port`/`SSEHub`/`HELP_DOC_NAME_RE`/`_bind_parent_lifecycle`/`_claude_watchdog_loop`/`_proc_starttime`/`_start_claude_watchdog` 被 import | 门面 MUST re-export 全部 |

### D4：隐性消费方——`bin/gen-route-map.py`

`bin/gen-route-map.py` 以**文本扫描** `server.py` 的 `path == "/api/..."` 字面量生成路由地图（`tests/test_planner_route_map.py` 消费）。

实测约束（三条 MUST 同步，缺一即静默退化）：

1. `scan_server_routes`（`bin/gen-route-map.py:38`）硬编码 `root/"core"/"dashboard"/"server.py"`（`:46`）；调用点 regex 为 `path\s*(?:==|startswith|endswith)\s*\(?\s*"([^"]+)"`（`:52`）。路由迁入 `routes/` 子包或改为表驱动后，此文件将扫不到任何条目。MUST 同步为扫描 `routes/` 子包全部模块，或直接改读表驱动路由表（后者的 matcher 若为 regex，须同步 `:52` 的提取逻辑）。
2. **方法归属启发式**（`:56-67`）以「行号回看 60 行内是否出现 `_handle_api_post` / `_handle_api_delete`」判定 POST/DELETE。迁移后单个资源子模块内不再含这两个方法名，此启发式会**静默把所有条目判成 GET**。MUST 改为按子模块/路由表显式声明方法归属，MUST NOT 依赖回看启发式。
3. **自检 grep 源**（`:126`、`:136`）同样硬编码 `core/dashboard/server.py`。MUST 与 (1) 使用**同一文件集合**，否则「启发式候选数 vs 解析条目数」两侧同时归零、差值 0，自检**空洞通过**而不报警。

覆盖回归兜底：`tests/test_planner_route_map.py` 的自检用例（`:271-296`）以 `tmp_path` 伪造项目为根，**不消费本仓**，因此无法发现本仓地图退化。task 4.6 MUST 另加一条断言——对本仓重构前后各生成一次地图，**条目数不得减少**（`(path, method)` 集合相等或为超集）。

### D5：跨组调用与私有回引

- `Dispatcher._run_agent_worker`（742 行）扇出到 5 个组 10+ 方法；`WorktreeManager._merge_back_from_branch_locked`（208 行）横跨 G4/G5/G6/G1。MUST 采用 `refactor-verification-module` D10 的「跨组调用经组合根注入，禁止子模块互相 import」——同一类的各组方法经宿主实例 `self.<method>` 协作（搬移后仍是同一类的方法，只是文件不同，可用 mixin 或把组方法设为模块函数并注入宿主）。
- `dispatch.py` 有 **52 个 `self._pm._X` 私有回引目标（130 处）**；若沿用 verification 的 context 注入先例，须**逐名登记**。本变更 MUST 至少完成「私有回引清单落盘」，是否本轮全部消解由阶段 3 裁决（可降级为后续 spec）。
- **server 侧同一约定同样适用**（表 C 未声明，此处补齐）：`DashboardHandler`（`core/dashboard/server.py:290`，基类 `BaseHTTPRequestHandler`）的 H0–H10 各组 MUST 采用与上两条**同一模式**——或 mixin（`DashboardHandler` 继承各组 mixin，MRO 中资源组须排在 `BaseHTTPRequestHandler` 之前），或组方法设为模块函数并经宿主实例注入。MUST NOT 出现「部分组 mixin、部分组注入」的混用，MUST NOT 让任何子模块反向 import `core/dashboard/routes/base.py` 形成环。

### D6：防止引入新的静态依赖环

- server 的子路由模块 MUST NOT 反向 import 或回塞常量到 `core.dashboard.data`（避免 data↔server 双向）。
- dispatch 的 repair-lane 子模块 MUST NOT 为便利直接 import `core.worktree_manager`（现状经 `self._pm.agent_runner` 属性链间接访问，无边）；MUST 继续走属性链 / 注入。

### D7：不使用绝对行号锚定

任务与交付物以方法名 / 类名 / 路由资源锚定。

## Risks / Trade-offs

- **[风险] 同名包遮蔽致中间态 import 失败** → 缓解：D2 先改名入包。
- **[风险] 类级状态（`_rehearsal_*`、queue 状态）跨组丢失** → 缓解：D3 钉死归属；队列状态属性整体随 Q 组迁移，engine property 委托链不变。
- **[风险] `time`/`subprocess` 模块级 patch 失效** → 缓解：D3 延迟解析。
- **[风险] route-map 静默退化** → 缓解：D4 三条 MUST 同步（扫描源、方法归属启发式、自检 grep 源）+ 本仓条目数不减少的回归断言。
- **[风险] 拆分引入新环** → 缓解：D6 显式禁止。
- **[风险] 路由分离改变匹配顺序** → 缓解：D1 保留 `endswith` 顺序陷阱，表驱动按序匹配。

## Migration Plan

1. 阶段 0：三文件 characterization tests（重点补测盲区：G5/G6、B 组 `_on_*_recovery`、adjudication）；基线失败集合；疑点清单。
2. 阶段 1：worktree_manager → 子包。
3. 阶段 2：dispatch → 子包。
4. 阶段 3：server → routes/ 子包 + 表驱动分派 + `bin/gen-route-map.py` 同步。
5. 阶段 4：全量回归、patch 缝隙专项、re-export 校验。

回滚：各阶段独立 commit。

## Open Questions

- dispatch 的 52 个 `_pm._X` 私有回引是否本轮全消解？（倾向落盘清单 + 本轮只消解高频 5 个，其余后续）
- `WorktreeManager` 拆包用 mixin 还是「模块函数 + 宿主注入」？（实现阶段按组内互调密度决定，倾向 mixin）

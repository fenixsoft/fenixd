# Contract Inventory: refactor-giant-classes

> 本文件以 AST/静态解析结果为据，逐一落位三巨型类全部方法、伴生类、模块级名到 design D1 分组表。
> 清点时间：2026-09-17，源文件行数：worktree_manager 4185 / dispatch 3926 / server 2843。

---

## A. WorktreeManager（83 方法 → `core/worktree_manager/` 子包）

**AST 计数：83 方法**，与 design D1 表 A 逐项比对，**无未归属项**。

### G1 创建/销毁生命周期 → `lifecycle.py`（10 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `__init__` | 144 |
| 2 | `create` | 207 |
| 3 | `has_active_lock` | 340 |
| 4 | `_seed_spec` | 349 |
| 5 | `ensure_spec_committed` | 421 |
| 6 | `cleanup` | 612 |
| 7 | `_snapshot_dirty_worktree` | 742 |
| 8 | `cleanup_orphans` | 797 |
| 9 | `has_active_worktree` | 858 |
| 10 | `refresh_locks` | 906 |

### G2 遗产/复用注册表 → `legacy_registry.py`（11 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `register_legacy` | 951 |
| 2 | `get_legacy` | 994 |
| 3 | `consume_legacy` | 1005 |
| 4 | `has_legacy` | 1053 |
| 5 | `keep_for_reuse` | 1062 |
| 6 | `get_reuse_record` | 1095 |
| 7 | `mark_reused` | 1105 |
| 8 | `_take_reusable_worktree` | 1112 |
| 9 | `_maybe_register_legacy_for_stale_lock` | 1146 |
| 10 | `_guess_branch_from_worktree` | 1168 |
| 11 | `_reclaim_expired_legacy` | 1183 |

### G3 锁治理/进程判活 → `locks.py`（10 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_lock_spec_name` | 1254 |
| 2 | `_register_spec_locks` | 1258 |
| 3 | `_release_spec_locks` | 1269 |
| 4 | `_lock_young` | 1277 |
| 5 | `_spec_process_alive` | 1292 |
| 6 | `_pgrep_spec_process` | 1313 |
| 7 | `_latest_stream_mtime` | 1338 |
| 8 | `_worktree_has_live_process` | 1364 |
| 9 | `_kill_worktree_strays` | 1383 |
| 10 | `_pid_alive` | 1452 |

### G4 merge-back 主链 → `mergeback.py`（12 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `get_branch_name` | 2156 |
| 2 | `merge_back` | 3331 |
| 3 | `merge_back_from_branch` | 2160 |
| 4 | `_detect_wip_overlap` | 2213 |
| 5 | `_merge_tree_supported` | 2268 |
| 6 | `_rehearse_merge_from_branch` | 2295 |
| 7 | `_parse_merge_tree_conflict_paths` | 2362 |
| 8 | `_rehearsed_path_is_ignored_du` | 2379 |
| 9 | `_merge_back_from_branch_locked` | 2399 |
| 10 | `_backup_untracked_spec_files` | 470 |
| 11 | `_drop_backup` | 541 |
| 12 | `_restore_backup` | 589 |

### G5 构建产物冲突/dist 重建 → `dist_conflicts.py`（8 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_resolve_build_artifact_conflicts` | 2607 |
| 2 | `_run_dist_build` | 2775 |
| 3 | `_rebuild_dist_after_merge` | 2837 |
| 4 | `_artifact_paths` | 2939 |
| 5 | `_parse_merge_blockers` | 2960 |
| 6 | `_list_unmerged_files` | 1873 |
| 7 | `_collect_conflict_paths` | 1901 |
| 8 | `_heal_unmerged_files` | 1932 |

### G6 主树还原/autostash 治理 → `stash_guard.py`（9 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_list_dirty_tracked_files` | 1495 |
| 2 | `ensure_clean_tree` | 1530 |
| 3 | `restore_after_merge` | 1582 |
| 4 | `_drop_superseded_stash_entry` | 1681 |
| 5 | `reclaim_stale_autostash` | 1762 |
| 6 | `_untrack_ignored_local_changes` | 2988 |
| 7 | `_discard_identical_local_changes` | 3073 |
| 8 | `_purge_ignored_brought_in` | 3153 |
| 9 | `_resolve_ignored_modify_delete_conflicts` | 3241 |

### G7 陈旧清扫 → `stale_sweep.py`（3 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `cleanup_stale_worktrees` | 1967 |
| 2 | `_read_state_entries` | 2070 |
| 3 | `_branch_protected_by_state` | 2106 |

### G8 查询/枚举（纯 git 只读）→ `queries.py`（16 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_spec_from_worktree_name` | 1461 |
| 2 | `_spec_from_branch` | 1476 |
| 3 | `file_exists_on_branch` | 3366 |
| 4 | `is_available` | 3418 |
| 5 | `create_worktree_on_branch` | 3471 |
| 6 | `find_worktree_path` | 3539 |
| 7 | `find_worktree_by_spec` | 3575 |
| 8 | `find_worktrees_by_spec` | 3660 |
| 9 | `find_branches_by_spec` | 3707 |
| 10 | `_wt_name_matches_spec` | 3870 |
| 11 | `has_pending_merge` | 3900 |
| 12 | `pending_merge_since` | 3922 |
| 13 | `_impl_branch_owned_by_spec` | 4010 |
| 14 | `branch_exists` | 4038 |
| 15 | `branch_tip` | 4053 |
| 16 | `find_implementer_worktree` | 3345 |

### G9 repair/resume 站点认领 → `repair_site.py`（4 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `repair_site_facts` | 4077 |
| 2 | `resolve_repair_site` | 4123 |
| 3 | `resolve_resume_site` | 4154 |
| 4 | `claim_legacy_for_repair` | 4168 |

### 数据类 → `types.py`

| 类 | 方法 | 行号 |
|---|------|------|
| `MergeConflictInfo` | `__init__`、`__iter__`、`__bool__`、`__repr__` | 66 |

### 门面 → `__init__.py` re-export 清单

| re-export | 类型 |
|---|---|
| `WorktreeManager` | class |
| `MergeConflictInfo` | class |
| `STALE_LOCK_IDLE_SECONDS` | 常量 |
| `LEGACY_GRACE_SECONDS` | 常量 |
| `PROCESS_SCAN_CACHE_SECONDS` | 常量 |
| `AUTOSTASH_MSG_PREFIX` | 常量 |
| `DASHBOARD_STATIC_ROOT` | 常量 |
| `WT_AVAILABLE` | 常量 |
| `WT_REBUILDABLE` | 常量 |
| `WT_UNAVAILABLE` | 常量 |
| `_is_claude_process` | 别名（→ `core.proc_utils.is_claude_process`） |
| `_is_build_artifact_path` | 函数 |

---

## B. Dispatcher（56 方法 → `core/pm_engine/dispatch/` 子包）

**AST 计数：56 方法**，与 design D1 表 B 逐项比对，**无未归属项**。

### Q 队列核心/worker → `queue.py`（8 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `__init__` | 37 |
| 2 | `_get_spec_priority` | 253 |
| 3 | `_enqueue` | 260 |
| 4 | `_enqueue_front` | 277 |
| 5 | `_aging_bonus` | 305 |
| 6 | `_effective_priority` | 343 |
| 7 | `_process_queue` | 347 |
| 8 | `_run_agent_worker` | 661 |

### B 退避/瞬时恢复排程 → `backoff.py`（9 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_dispatch_backoff_schedule` | 60 |
| 2 | `_handle_dispatch_lock_conflict` | 81 |
| 3 | `_schedule_backoff_retry` | 140 |
| 4 | `_schedule_instant_fail_recovery` | 153 |
| 5 | `_schedule_instant_fail_recovery_locked` | 169 |
| 6 | `_on_instant_fail_recovery` | 186 |
| 7 | `_schedule_transient_recovery` | 204 |
| 8 | `_schedule_transient_recovery_locked` | 219 |
| 9 | `_on_transient_recovery` | 239 |

### V 交付物裁定/dispute → `adjudication.py`（9 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_record_impl_diagnosis` | 1565 |
| 2 | `_build_dispute_judge_input` | 1816 |
| 3 | `_dispute_spec_context` | 1872 |
| 4 | `_read_dispute_verdicts` | 1925 |
| 5 | `_commit_softened_declaration` | 1974 |
| 6 | `_preclassify_missing` | 2012 |
| 7 | `_adjudicate_deliverable_missing` | 2161 |
| 8 | `_redispatch_for_missing` | 2445 |
| 9 | `_redispatch_tasks_relint` | 2505 |

### R 失败回滚/诊断上报 → `rollback.py`（4 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_rollback_failed_dispatch` | 1640 |
| 2 | `_report_stash_pop_conflict` | 1710 |
| 3 | `_honest_exit_gap` | 1428 |
| 4 | `_dispatch_backoffed` | 1468 |

### F fast-track 车道 → `fast_track.py`（17 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_fast_track_scale_precheck` | 1484 |
| 2 | `_scale_precheck_config` | 1525 |
| 3 | `_downgrade_fast_track_scale` | 1534 |
| 4 | `_run_fast_track_worker` | 2549 |
| 5 | `_run_fast_track_flow` | 2581 |
| 6 | `_harvest_fast_track_worktree` | 2771 |
| 7 | `_keep_fast_track_worktree` | 2795 |
| 8 | `_release_fast_track_worktree` | 2813 |
| 9 | `_reconcile_and_merge` | 2827 |
| 10 | `_hard_check_fast_track` | 3570 |
| 11 | `_fast_track_advance_to_verified` | 3661 |
| 12 | `_rewrite_fast_track_to_full` | 3701 |
| 13 | `_escalate_to_full_mode` | 3732 |
| 14 | `_handle_fast_track_missing_result_merge` | 3770 |
| 15 | `_handle_fast_track_failure` | 3806 |
| 16 | `_handle_fast_track_zero_change` | 3865 |
| 17 | `_handle_fast_track_deliverable_gate` | 3893 |

### P merge-back 修复车道 → `repair_lane.py`（9 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_direct_rehearsed_to_repair` | 2948 |
| 2 | `_should_enter_repair` | 2982 |
| 3 | `_dispatch_repair_lane` | 3013 |
| 4 | `_claim_repair_site` | 3108 |
| 5 | `_run_repair_worker` | 3127 |
| 6 | `_check_repair_commit_facts` | 3334 |
| 7 | `_handle_remerge_failure` | 3404 |
| 8 | `_fallback_after_repair` | 3459 |
| 9 | `_repair_conflict_summary` | 3551 |

### 门面 → `__init__.py` re-export 清单

| re-export | 类型 |
|---|---|
| `Dispatcher` | class |
| `DEFAULT_DISPATCH_BACKOFF_SCHEDULE` | 常量 |
| `MAX_REPAIR_ROUNDS_PER_FAILURE` | 常量 |

---

## C. DashboardHandler（80 方法 + 伴生类 14 方法 + 10 模块函数 → `core/dashboard/` 子包）

**AST 计数：DashboardHandler 80 方法**，与 design D1 表 C 逐项比对，**无未归属项**。

### H0 HTTP 底座（共享）→ `routes/base.py`（12 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `do_GET` | 303 |
| 2 | `do_HEAD` | 306 |
| 3 | `do_POST` | 309 |
| 4 | `do_DELETE` | 312 |
| 5 | `log_message` | 315 |
| 6 | `_handle` | 319 |
| 7 | `_handle_inner` | 331 |
| 8 | `_read_json_body` | 2219 |
| 9 | `_json` | 2570 |
| 10 | `_error` | 2581 |
| 11 | `_wants_gzip` | 2544 |
| 12 | `_maybe_gzip` | 2547 |

### H1 路由分派链 → `routes/base.py`（3 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_handle_api` | 371 |
| 2 | `_handle_api_post` | 2133 |
| 3 | `_handle_api_delete` | 2209 |

### H2 project/overview → `routes/project_routes.py`（10 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_api_projects` | 422 |
| 2 | `_api_overview` | 447 |
| 3 | `_project_query_or_error` | 1392 |
| 4 | `_resolve_project_or_400` | 1749 |
| 5 | `_api_project_lifecycle` | 1772 |
| 6 | `_run_project_lifecycle_locked` | 1801 |
| 7 | `_api_project_install_hosting` | 1856 |
| 8 | `_api_project_delete` | 1882 |
| 9 | `_api_project_describe` | 2301 |
| 10 | `_project_from_query` | 2396 |

### H3 spec 族 → `routes/spec_routes.py`（17 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_api_specs` | 450 |
| 2 | `_api_spec_detail` | 461 |
| 3 | `_api_spec_doc` | 476 |
| 4 | `_api_spec_error_clear` | 592 |
| 5 | `_api_spec_priority` | 623 |
| 6 | `_api_spec_freeze` | 665 |
| 7 | `_api_spec_unfreeze` | 691 |
| 8 | `_api_spec_start_after` | 713 |
| 9 | `_api_spec_freeze_config` | 764 |
| 10 | `_api_spec_budget` | 819 |
| 11 | `_api_spec_archive` | 875 |
| 12 | `_api_spec_promote` | 939 |
| 13 | `_api_spec_task_reflow` | 970 |
| 14 | `_api_spec_re_review` | 1008 |
| 15 | `_api_spec_approve_push` | 1044 |
| 16 | `_api_spec_delete` | 1093 |
| 17 | `_api_spec_admin_invoke` | 1135 |

### H4 run/event → `routes/run_routes.py`（5 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_api_run_cancel` | 1182 |
| 2 | `_api_run` | 1233 |
| 3 | `_api_run_watch` | 1247 |
| 4 | `_api_events` | 1261 |
| 5 | `_api_hooks_audit` | 1285 |

### H5 配置/提示词/todo/verify-yaml → `routes/settings_routes.py`（12 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_api_config_get` | 1274 |
| 2 | `_api_config_post` | 2243 |
| 3 | `_api_config_sync_from_user` | 2273 |
| 4 | `_api_prompts_get` | 1307 |
| 5 | `_read_project_extra` | 1339 |
| 6 | `_api_prompts_post` | 1351 |
| 7 | `_api_todo_get` | 1407 |
| 8 | `_api_todo_post` | 1430 |
| 9 | `_api_verify_yaml_get` | 1456 |
| 10 | `_api_verify_yaml_post` | 1479 |
| 11 | `_api_verify_yaml_template` | 1522 |
| 12 | `_api_verify_yaml_autodraft_post` | 1536 |

### H6 alerts → `routes/alert_routes.py`（4 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_api_alerts` | 1621 |
| 2 | `_api_admin_activities` | 1670 |
| 3 | `_api_alert_handled` | 1700 |
| 4 | `_api_alerts_clear` | 1727 |

### H7 evolution → `routes/evolution_routes.py`（8 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_evolution_state_machine` | 1935 |
| 2 | `_api_evolution_items` | 1941 |
| 3 | `_api_evolution_analysis` | 1952 |
| 4 | `_api_evolution_draft` | 1967 |
| 5 | `_api_evolution_accept` | 1991 |
| 6 | `_api_evolution_reject` | 2041 |
| 7 | `_api_evolution_delete` | 2065 |
| 8 | `_api_evolution_clear_todo` | 2091 |

### H8 help → `routes/help_routes.py`（3 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_api_help_docs` | 526 |
| 2 | `_help_doc_title` | 515 |
| 3 | `_api_help_doc` | 558 |

### H9 SSE → `routes/sse_routes.py`（3 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_handle_sse` | 2404 |
| 2 | `_sse_client_gone` | 2447 |
| 3 | `_sse_send` | 2467 |

### H10 静态/截图 → `routes/static_routes.py`（3 方法）

| # | 方法 | 行号 |
|---|------|------|
| 1 | `_serve_static` | 2484 |
| 2 | `_serve_screenshot` | 2507 |
| 3 | `_send_file` | 2554 |

> 注：H0+H1=15，H2=10，H3=17，H4=5，H5=12，H6=4，H7=8，H8=3，H9=3，H10=3 → 80 方法 ✓（`_wants_gzip`/`_maybe_gzip` 属 H0，见上）

### 伴生类

**SSEConnection**（`core/dashboard/sse.py`）— 2 方法

| # | 方法 | 行号 |
|---|------|------|
| 1 | `__init__` | 103 |
| 2 | `send` | 108 |

**SSEHub**（`core/dashboard/sse.py`）— 7 方法

| # | 方法 | 行号 |
|---|------|------|
| 1 | `__init__` | 123 |
| 2 | `register` | 128 |
| 3 | `unregister` | 142 |
| 4 | `watch` | 154 |
| 5 | `unwatch` | 160 |
| 6 | `is_watched` | 166 |
| 7 | `broadcast` | 146 |

**DashboardHTTPServer**（`core/dashboard/http_server.py`）— 5 方法

| # | 方法 | 行号 |
|---|------|------|
| 1 | `__init__` | 234 |
| 2 | `_try_acquire_request_slot` | 248 |
| 3 | `_release_request_slot` | 256 |
| 4 | `projects` | 260 |
| 5 | `project_by_name` | 279 |

### 模块函数（保留在 `server.py`，与 `DashboardHandler` 组装）— 10 函数

| # | 函数 | 行号 |
|---|------|------|
| 1 | `find_free_port` | 171 |
| 2 | `_project_lifecycle_lock` | 185 |
| 3 | `_find_dashboard_occupant` | 2592 |
| 4 | `_is_dashboard_serve_cmd` | 2650 |
| 5 | `_proc_starttime` | 2655 |
| 6 | `_claude_watchdog_loop` | 2669 |
| 7 | `_start_claude_watchdog` | 2678 |
| 8 | `_bind_parent_lifecycle` | 2714 |
| 9 | `serve` | 2757 |
| 10 | `_is_process_alive` | 2838 |

### 模块级常量/变量（保留在 `server.py`）

| # | 名称 | 行号 |
|---|------|------|
| 1 | `logger` | 77 |
| 2 | `STATIC_DIR` | 79 |
| 3 | `ALLOWED_IMAGE_EXT` | 80 |
| 4 | `FRAMEWORK_ROOT` | 83 |
| 5 | `HELP_DOCS_DIR` | 84 |
| 6 | `HELP_DOC_NAME_RE` | 87 |
| 7 | `MAX_SSE_CONNECTIONS` | 90 |
| 8 | `MAX_SERVER_THREADS` | 91 |
| 9 | `SSE_CLIENT_POLL_INTERVAL` | 94 |
| 10 | `MAX_POST_BODY` | 287 |

### 门面 re-export（`server.py` 保留，供 `start_daemon`/`stop_daemon` 字符串 patch）

| re-export | 来源 |
|---|---|
| `start_daemon` | `core.fenix_session` |
| `stop_daemon` | `core.fenix_session` |
| `BaseHTTPRequestHandler` | `http.server` |
| `ThreadingHTTPServer` | `http.server` |
| `dashboard_data` | `core.dashboard.data` |
| `Registry` | `registry` |
| `FileWatcher` | `watcher` |
| `AGENT_PROMPT_DIR` | `core.agent_runner.prompt_builder` |
| `AGENT_PROMPT_FILES` | `core.agent_runner.prompt_builder` |
| `project_agents_dir` | `core.agent_runner.prompt_builder` |
| `AdminStore` | `core.admin_store` |
| `SIGNAL` | `core.admin_store` |

---

## 汇总校验

| 类 | AST 方法数 | D1 声明数 | 匹配 |
|---|---|---|---|
| `WorktreeManager` | 83 | 83 | ✅ |
| `Dispatcher` | 56 | 56 | ✅ |
| `DashboardHandler` | 80 | 80 | ✅ |
| `SSEConnection` | 2 | 2 | ✅ |
| `SSEHub` | 7 | 7 | ✅ |
| `DashboardHTTPServer` | 5 | 5 | ✅ |
| 模块函数（server.py） | 10 | 10 | ✅ |
| **合计** | **243** | **243** | **✅ 无未归属项** |

---

## D3：patch 缝隙基线（设计 D3，只读记录）

### worktree_manager.py 缝隙

| 缝隙 | 测试引用点 | 数量 | 保持策略 |
|---|---|---|---|
| `patch("core.worktree_manager.subprocess.run")` | tests/test_characterization_giant_classes.py:207-480 等 | 11 处 | 调用点经 `core.worktree_manager` 命名空间延迟解析（D3） |
| `patch("core.worktree_manager.time.time")` | tests/test_dual_dispatch_and_freeze.py:133 | 1 处 | 同上 |
| 类属性 `_rehearsal_probe_done`/`_rehearsal_supported`（测试直接赋值） | tests/test_merge_tree_rehearsal.py:99-100 `WorktreeManager._rehearsal_probe_done = False` | 2 处 | MUST 仍挂 `WorktreeManager` 类命名空间 |
| `WorktreeManager._impl_branch_owned_by_spec` staticmethod 类直调 | tests/test_recovery_watch_transition_guard.py:243-257 | 4 处 | MUST 留类命名空间 |
| 8 常量 + `MergeConflictInfo` + `_is_claude_process` | 门面 re-export（12 项） | 12 项 | 门面 MUST re-export 全部 |
| worktree_manager.py 内 subprocess./time. 调用总数 | 163 处 | — | 子模块调用点须保持延迟解析 |

### dispatch.py 缝隙

| 缝隙 | 测试引用点 | 数量 | 保持策略 |
|---|---|---|---|
| `monkeypatch.setattr(_dispatch_mod, "time", _tick)` | tests/test_repair_lane_dedup.py:303-309 | 1 处 | 凡用 `time` 的组经 `core.pm_engine.dispatch` 命名空间解析 |
| `Dispatcher._dispatch_backoffed` 生产类直调 | core/admin_monitor.py:427 | 1 处 | MUST 留类命名空间 |
| `Dispatcher._dispatch_backoffed` engine wrapper | core/pm_engine/engine.py:3029-3030 | 1 处 | 同上 |
| 2 常量 | `DEFAULT_DISPATCH_BACKOFF_SCHEDULE`、`MAX_REPAIR_ROUNDS_PER_FAILURE` | 2 项 | 门面 re-export |
| dispatch.py 内 time. 调用 | time.time() 4 处 + time.monotonic() 1 处 | 5 处 | 调用点须保持 `core.pm_engine.dispatch` 命名空间延迟解析 |

### server.py 缝隙

| 缝隙 | 测试引用点 | 数量 | 保持策略 |
|---|---|---|---|
| monkeypatch `HELP_DOCS_DIR` | test_dashboard_help_api.py（11 处） | 11 处 | 调用点经 `core.dashboard.server` 命名空间延迟解析 |
| monkeypatch `FRAMEWORK_ROOT` | test_dashboard_evolution_api.py:86/167 | 2 处 | 同上 |
| monkeypatch `MAX_SSE_CONNECTIONS` | test_dashboard_connection_limit.py:88 | 1 处 | 同上 |
| monkeypatch `MAX_SERVER_THREADS` | test_dashboard_connection_limit.py:141/154 | 2 处 | 同上 |
| monkeypatch `SSE_CLIENT_POLL_INTERVAL` | test_dashboard_connection_limit.py:80 | 1 处 | 同上 |
| monkeypatch `ALLOWED_IMAGE_EXT`（未发现测试 patch，但设计 D3 列为预留） | — | 0 处 | 可用即可 |
| 字符串 patch `start_daemon`/`stop_daemon`（9 处） | test_dashboard_api.py:357/359/385/404/406 + test_supervisor_hosting.py:564/566/579/581 | 9 处 | 调用点 MUST 经 `core.dashboard.server` 命名空间延迟解析 |
| 10 个被 import 名（门面 re-export） | see table C 门面 re-export | 10 项 | 门面 MUST re-export 全部 |

---

## D4：隐性消费方（bin/gen-route-map.py）基线

| 项目 | 基线现状 | 设计 D4 三条 MUST |
|---|---|---|
| `scan_server_routes`（bin/gen-route-map.py:38）扫描源 | 硬编码 `root/"core"/"dashboard"/"server.py"`（:46） | MUST 同步为扫描 `routes/` 子包或表驱动路由表 |
| 方法归属启发式（:56-67） | 回看 60 行内 `_handle_api_post`/`_handle_api_delete` | MUST 改为按子模块/路由表显式声明 |
| 自检 grep 源（:126/:136） | 硬编码 `core/dashboard/server.py` | MUST 与扫描源使用同一文件集合 |
| 消费方 | tests/test_planner_route_map.py 自检用例（:271-296），tmp_path 伪造根 | 任务 4.6 MUST 另加本仓覆盖回归断言 |

---

## D5：Dispatcher 私有回引清单（130 处 → 52 目标）

高频 5 目标（消解候选，design D5 要求本轮至少落盘清单）：

| 排名 | 目标 `self._pm._X` | 调用次数 |
|---|---|---|
| 1 | `_get_config` | 15 |
| 2 | `_enqueue_front` | 13 |
| 3 | `_enqueue` | 7 |
| 4 | `_fallback_after_repair` | 6 |
| 5 | `_deliverable_gate_missing` | 5 |

全部 52 目标（按频率降序）：

| 目标 | 次数 | 目标 | 次数 | 目标 | 次数 |
|---|---|---|---|---|---|
| `_get_config` | 15 | `_enqueue_front` | 13 | `_enqueue` | 7 |
| `_fallback_after_repair` | 6 | `_deliverable_gate_missing` | 5 | `_process_queue` | 4 |
| `_should_enter_repair` | 4 | `_dispatch_repair_lane` | 4 | `_on_spec_ready` | 3 |
| `_instant_fail_cooled` | 3 | `_read_implementer_result` | 3 | `_reconcile_impl_budget` | 3 |
| `_merge_fingerprint` | 3 | `_clear_dispatch_conflict` | 3 | `_sync_task_progress` | 3 |
| `_exempt_dead_run_budget` | 3 | `_get_spec_priority` | 2 | `_effective_priority` | 2 |
| `_dispatch_backoffed` | 2 | `_check_impl_budget_exhausted` | 2 | `_check_spec_content_missing` | 2 |
| `_increment_impl_run_budget_used` | 2 | `_partial_attribution` | 2 | `_note_unattainable_todos` | 2 |
| `_implementer_zero_change` | 2 | `_write_impl_result_snapshot` | 2 | `_cleanup_shared_result_file` | 2 |
| `_rollback_failed_dispatch` | 2 | `_dispatch_backoff_schedule` | 1 | `_signal_dispatch_stalled` | 1 |
| `_schedule_backoff_retry` | 1 | `_instant_fail_cooldown_until` | 1 | `_aging_bonus` | 1 |
| `_global_transient_break_active` | 1 | `_is_fix_spec` | 1 | `_sibling_repair_active` | 1 |
| `_run_agent_worker` | 1 | `_disputed_deliverables` | 1 | `_adjudicate_deliverable_missing` | 1 |
| `_tasks_md_relint_from_branch` | 1 | `_report_stash_pop_conflict` | 1 | `_run_verification_pipeline` | 1 |
| `_git_commit` | 1 | `_implementation_branch_has_commits` | 1 | `_tasks_md_relint_from_worktree` | 1 |
| `_claim_repair_site` | 1 | `_run_repair_worker` | 1 | `_check_repair_commit_facts` | 1 |
| `_handle_remerge_failure` | 1 | `_find_implementer_worktree` | 1 | `_env_whitewash_gate` | 1 |
| `_on_spec_verified` | 1 | | | | |

> 注：高频 5 个由 design D5 要求本轮至少登记，是否本轮消解由阶段 3 裁决。

---

## 阶段 0 基线失败集合（run_full_suite.py --baseline HEAD，2026-09-17）

分类：**存量**（baseline_only）—— 当前失败 ⊆ 基线失败，无本次引入回归。

| 失败用例 | 归类 |
|---|---|
| `tests/test_dashboard_api.py::TestServerAPI::test_index_served` | 存量 |
| `tests/test_dashboard_api.py::TestServerAPI::test_static_root_fallback_to_dist` | 存量 |
| `tests/test_task_track.py::TestCliWarning::test_missing_tasks_md_silent` | 存量 |
| `tests/test_task_track.py::TestCliWarning::test_parseable_tasks_md_no_warning` | 存量 |
| `tests/test_task_track.py::TestCliWarning::test_undotted_format_still_parses` | 存量 |
| `tests/test_task_track.py::TestCliWarning::test_unparseable_tasks_md_prints_warning` | 存量 |

> 基线 worktree（HEAD）多一个环境差异失败：`tests/test_callsite_arity_guard.py::TestArityGuardTeeth::test_node_modules_vendored_excluded`（基线 worktree 缺 node_modules）。当前 HEAD 不失败此项，属基线环境差异非代码问题。

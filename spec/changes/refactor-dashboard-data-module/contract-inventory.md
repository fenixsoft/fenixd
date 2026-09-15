# Contract Inventory — core/dashboard/data.py

> 清点时间：2026-09-15 | data.py 版本：31252f71（HEAD）
> 扫描方法：AST 顶层节点 + grep 属性访问 + alias-based AST 解析

## 1. 顶层名字（四类）

### 1.1 函数（115 个 def）+ 类（4 个 class）= 119 个

```
get_alerts get_unhandled_alerts get_resolved_alerts mark_alert_handled
mark_all_alerts_handled alerts_summary get_admin_activities
request_admin_invoke request_run_cancel is_spec_frozen freeze_spec unfreeze_spec
reclassify_infra_rounds promote_spec reflow_spec re_review_spec
_write_scheduling_kick_signal get_spec_start_after get_frozen_until
set_spec_start_after set_spec_budget configure_spec_freeze
request_spec_approve_push resolve_spec_dir get_spec_doc _read_spec_scenarios
clear_spec_error set_spec_priority soft_delete_spec is_spec_archived
archive_spec auto_archive_check parse_state find_implementer_worktree
_should_overlay parse_tasks task_progress tasks_note run_task_progress
run_activity                                          ← D3 表外（见 §5）
count_scenarios count_generated_scenarios spec_generation_progress
_log_index_path _build_log_block_index _write_log_index
_update_log_block_index _load_log_index _read_log_tail_window
_iter_tail_log_entries _norm_utc_iso _read_log_window_from
get_recent_events record_project_event
parse_verify_progress parse_report parse_test_scenarios
parse_run_result_scenarios list_screenshots _fold_summary
_load_run_result _run_result_verdict_and_bugs
_verdict_from_run_result parse_verdict parse_bugs parse_filtered_failures
classify_run _resolve_run_file _first_run_event_ts get_runs _read_run_lines
_parse_run_lines get_run_events read_run_events_between active_run_count
daemon_health hosting_state project_summary _spec_total_duration
_resolve_global_impl_run_budget spec_summary _stat_sig _runs_by_spec_sigs
_spec_dep_sigs _backtrack_reason _load_billing_config _run_tail_insights
compute_run_cost _split_llm_marker _admin_events_for_spec
get_spec_timeline _collapse_timeline _parse_iso_ts _timeline_sort_key
_ts_delta _timeline_with_retry _cost_summary_from_timeline
spec_detail _token_usage_view _parse_spec_ts _updated_spec_counts
_token_recent_entries _degraded_project overview
_managed_key_sources _managed_admin_keys read_config _config_file_sig
read_effective_config _deep_merge_managed write_config sync_config_from_user
read_evolution_items read_evolution_analysis read_evolution_draft
```

**Classes（4 个）**：`InvalidSpecName` `InvalidSpecDoc` `InvalidPriority` `SummaryIndex`

### 1.2 模块级赋值/常量/别名（32 个）

```
ADMIN_INVOKE_REQUEST
CANCEL_RUN_REQUEST
SCHEDULING_KICK_REQUEST
APPROVE_PUSH_REQUEST
_SPEC_NAME_RE
_SPEC_DOC_WHITELIST
_parse_run_task_done          ← compat alias from core.run_task_track
_find_impl_run_file           ← compat alias from core.run_task_track
_LIVE_OVERLAY_STATUSES
LOG_INDEX_BLOCK
LOG_INDEX_TAIL_WINDOW
_LOG_INDEX_REBUILDS
_RUN_TERMINAL_STATUS_MAP
_RUN_STALE_SECONDS
_DAEMON_HEALTH_TTL
_DAEMON_HEALTH_CACHE
_HOSTING_STATE_TTL
_HOSTING_STATE_CACHE
_GLOBAL_BUDGET_CACHE
_GLOBAL_BUDGET_CACHE_MAX
_LIFECYCLE_ORDER
_MANAGED_KEYS
_AGENTS_MANAGED_SUBKEYS
USER_CONFIG_PATH              ← D8：留在门面，不随组迁移
_SOURCE_KEYS
_DEFAULT_SELF_REVIEW
_CONFIG_HEADER_COMMENT
_ADMIN_DEFAULTS
_EFFECTIVE_CONFIG_CACHE
_EFFECTIVE_CONFIG_CACHE_MAX
_SYNC_PAGE_KEYS
EVOLUTION_DOC_WHITELIST
```

### 1.3 导入后二次导出的名字（26 个绑定）

**标准库/第三方（13 个）**——外部无直接访问，但 `yaml` 被 `tests/test_dashboard_index.py:191` 以 `dash_data.yaml.safe_load` 访问，门面须 re-export：

```
copy json os re shutil tempfile threading time deque datetime timezone timedelta Path yaml
```

**内部跨模块导入（13 个）**——外部有直接访问的用 ★ 标注：

```
archive_spec_runs
infer_run_agent_type
run_spec_part
commit_archive_move
★ _is_running                   ← from core.fenix_session; 8 处 patch
★ find_impl_run_file             ← from core.run_task_track; 2 处引用
★ parse_run_task_done            ← from core.run_task_track; 2 处引用
FREEZE_ERROR_PREFIX
FROZEN_FIELD
parse_orig_status
INFRA_FAILURE_COUNT_FIELD
VERIFY_INFRA_ROUNDS_FIELD
```

> **总计顶层名字**：119（函数/类）+ 32（常量/别名）= **151**（较 design 预估 150 多 1，因近期新增 `run_activity`）。

---

## 2. 全仓对 `core.dashboard.data` 的属性访问清单

### 2.1 `from core.dashboard.data import X` + `core.dashboard.data.X` 直接属性访问（32 文件，51 个 distinct name）

| 文件 | 访问的 name |
|---|---|
| `bin/fenix_dashboard.py` | count_scenarios get_recent_events parse_state parse_tasks parse_verify_progress task_progress |
| `bin/fenix_process.py` | get_frozen_until get_spec_start_after is_spec_frozen parse_state spec_detail spec_summary |
| `bin/fenix_status.py` | alerts_summary daemon_health get_frozen_until get_runs get_spec_start_after is_spec_frozen parse_state read_effective_config spec_summary |
| `core/event_bus.py` | find_impl_run_file |
| `core/pm_engine/engine.py` | find_impl_run_file get_runs parse_run_task_done record_project_event |
| `core/pm_engine/verification.py` | parse_verify_progress request_admin_invoke |
| `fenixd.py` | auto_archive_check |
| `tests/.verify_probe_s1.py` | get_spec_timeline |
| `tests/.verify_probe_s2.py` | get_spec_timeline |
| `tests/.verify_probe_s3.py` | get_spec_timeline |
| `tests/.verify_probe_s5.py` | get_spec_timeline |
| `tests/.verify_probe_s6.py` | get_spec_timeline |
| `tests/test_alert_lifecycle.py` | get_resolved_alerts |
| `tests/test_config.py` | _is_running daemon_health overview project_summary |
| `tests/test_daily_self_review.py` | USER_CONFIG_PATH read_effective_config write_config |
| `tests/test_dashboard_api.py` | USER_CONFIG_PATH |
| `tests/test_dashboard_data.py` | InvalidSpecDoc InvalidSpecName USER_CONFIG_PATH _GLOBAL_BUDGET_CACHE _deep_merge_managed _parse_iso_ts _run_tail_insights active_run_count classify_run count_generated_scenarios get_runs get_spec_doc get_spec_timeline parse_bugs parse_run_result_scenarios parse_state parse_tasks parse_verdict parse_verify_progress project_summary read_config read_effective_config resolve_spec_dir set_spec_budget spec_summary sync_config_from_user tasks_note write_config |
| `tests/test_dashboard_evolution_api.py` | USER_CONFIG_PATH |
| `tests/test_dashboard_freeze.py` | configure_spec_freeze freeze_spec is_spec_frozen parse_state spec_summary unfreeze_spec |
| `tests/test_dashboard_index.py` | SummaryIndex |
| `tests/test_dashboard_mode.py` | spec_detail spec_summary |
| `tests/test_fenix_tui_reports.py` | USER_CONFIG_PATH |
| `tests/test_infra_budget_exempt.py` | reclassify_infra_rounds |
| `tests/test_retry_orphan_active_runs.py` | classify_run get_runs project_summary |
| `tests/test_spec_archive.py` | archive_spec auto_archive_check parse_state read_effective_config record_project_event spec_summary write_config |
| `tests/test_spec_scheduling.py` | configure_spec_freeze freeze_spec set_spec_start_after unfreeze_spec |
| `tests/test_spec_timeline_name_isolation.py` | get_spec_timeline |
| `tests/test_state_layout_contract.py` | parse_state |
| `tests/test_supervisor_hosting.py` | daemon_health hosting_state |
| `tests/test_system_settings_config.py` | read_config write_config |
| `tests/test_task_progress_protocol.py` | _RUN_STALE_SECONDS run_activity run_task_progress spec_detail spec_summary |
| `tests/test_task_track.py` | spec_detail tasks_note |
| `tests/test_verdict_evidence_taxonomy.py` | parse_bugs |
| `tests/test_verdict_visibility.py` | parse_bugs parse_filtered_failures spec_detail |
| `tests/test_verify_report_gate.py` | parse_verdict |

**Distinct accessed names（51 个）**：
`InvalidSpecDoc` `InvalidSpecName` `SummaryIndex` `USER_CONFIG_PATH` `_GLOBAL_BUDGET_CACHE` `_RUN_STALE_SECONDS` `_deep_merge_managed` `_is_running` `_parse_iso_ts` `_run_tail_insights` `active_run_count` `archive_spec` `auto_archive_check` `classify_run` `configure_spec_freeze` `count_generated_scenarios` `daemon_health` `find_impl_run_file` `freeze_spec` `get_resolved_alerts` `get_runs` `get_spec_doc` `get_spec_timeline` `hosting_state` `is_spec_frozen` `overview` `parse_bugs` `parse_filtered_failures` `parse_run_result_scenarios` `parse_run_task_done` `parse_state` `parse_tasks` `parse_verdict` `parse_verify_progress` `project_summary` `read_config` `read_effective_config` `reclassify_infra_rounds` `record_project_event` `request_admin_invoke` `resolve_spec_dir` `run_activity` `run_task_progress` `set_spec_budget` `set_spec_start_after` `spec_detail` `spec_summary` `sync_config_from_user` `tasks_note` `unfreeze_spec` `write_config`

### 2.2 alias-based 访问（`from core.dashboard import data as dash_data` → `dash_data.X`）（去误报后）

额外新增 names（与 2.1 合并去重后新增）：

| 文件（新文件） | 访问的 name |
|---|---|
| `tests/test_config.py` | _DAEMON_HEALTH_CACHE |
| `tests/test_cost_observability.py` | _token_usage_view |
| `tests/test_dashboard_api.py` | promote_spec |
| `tests/test_dashboard_fault_isolation.py` | overview parse_state project_summary |
| `tests/test_dashboard_index.py` | _config_file_sig _stat_sig read_effective_config spec_summary write_config yaml |
| `tests/test_dashboard_log_index.py` | LOG_INDEX_BLOCK LOG_INDEX_TAIL_WINDOW _LOG_INDEX_REBUILDS _log_index_path get_recent_events get_spec_timeline |
| `tests/test_dashboard_watcher.py` | SummaryIndex |
| `tests/test_dashboard_watcher_incremental.py` | SummaryIndex parse_state |
| `tests/test_model_billing.py` | _load_billing_config _run_tail_insights _split_llm_marker compute_run_cost get_spec_timeline parse_state read_config read_effective_config spec_detail write_config |
| `tests/test_run_cancel.py` | request_run_cancel |
| `tests/test_spec_approve_push.py` | APPROVE_PUSH_REQUEST _is_running request_spec_approve_push |
| `tests/test_stale_code_selfheal.py` | read_config read_effective_config write_config |
| `tests/test_supervisor_hosting.py` | daemon_health hosting_state |
| `tests/test_spec_archive.py` | get_recent_events |

**Merged accessed names（73 个 distinct，含常量、私有函数、模块名）**：
`APPROVE_PUSH_REQUEST` `InvalidSpecDoc` `InvalidSpecName` `LOG_INDEX_BLOCK` `LOG_INDEX_TAIL_WINDOW` `SummaryIndex` `_DAEMON_HEALTH_CACHE` `_GLOBAL_BUDGET_CACHE` `_LOG_INDEX_REBUILDS` `_RUN_STALE_SECONDS` `_config_file_sig` `_deep_merge_managed` `_load_billing_config` `_log_index_path` `_parse_iso_ts` `_run_tail_insights` `_split_llm_marker` `_stat_sig` `_token_usage_view` `active_run_count` `alerts_summary` `archive_spec` `auto_archive_check` `classify_run` `compute_run_cost` `configure_spec_freeze` `count_generated_scenarios` `count_scenarios` `daemon_health` `find_impl_run_file` `freeze_spec` `get_frozen_until` `get_recent_events` `get_resolved_alerts` `get_runs` `get_spec_doc` `get_spec_start_after` `get_spec_timeline` `hosting_state` `is_spec_frozen` `overview` `parse_bugs` `parse_filtered_failures` `parse_run_result_scenarios` `parse_run_task_done` `parse_state` `parse_tasks` `parse_verdict` `parse_verify_progress` `project_summary` `promote_spec` `read_config` `read_effective_config` `record_project_event` `request_admin_invoke` `request_run_cancel` `request_spec_approve_push` `resolve_spec_dir` `run_activity` `run_task_progress` `set_spec_budget` `set_spec_start_after` `spec_detail` `spec_summary` `sync_config_from_user` `tasks_note` `unfreeze_spec` `write_config` `yaml`

---

## 3. 各 import 模块的用途/归属

| import 来源 | 绑定名 | 用途 | 迁入组 |
|---|---|---|---|
| core.agent_runner.run_files | archive_spec_runs, infer_run_agent_type, run_spec_part | spec 归档/agent类型推断 | admin_actions / spec_archive 内使用 |
| core.archive_commit | commit_archive_move | commit 归档移动 | spec_archive 内使用 |
| core.fenix_session | _is_running | run 存活检查 | **门面保留**（D8，调用点延迟解析） |
| core.state_machine | FREEZE_ERROR_PREFIX, FROZEN_FIELD, parse_orig_status, INFRA_FAILURE_COUNT_FIELD, VERIFY_INFRA_ROUNDS_FIELD | 状态机常量/解析 | admin_actions / admin_alerts 内使用 |
| core.run_task_track | find_impl_run_file, parse_run_task_done | run 任务文件查找 | tasks 组（连同别名 _parse_run_task_done/_find_impl_run_file） |

---

## 4. 分组归属对账（D3 表）

**D3 表覆盖函数/类**：115 个 def + 4 个 class（共 119）— 全部出现在 D3 表中，除 `run_activity` 一条。

### 4.1 模块级常量随组归属（tasks.md §4.0）

| 常量 | 归入子模块 |
|---|---|
| `ADMIN_INVOKE_REQUEST` `CANCEL_RUN_REQUEST` `SCHEDULING_KICK_REQUEST` `APPROVE_PUSH_REQUEST` | `admin_actions.py` |
| `_SPEC_NAME_RE` `_SPEC_DOC_WHITELIST` | `spec_docs.py` |
| `_LIVE_OVERLAY_STATUSES` | `tasks.py` |
| `LOG_INDEX_BLOCK` `LOG_INDEX_TAIL_WINDOW` `_LOG_INDEX_REBUILDS` | `log_index.py` |
| `_RUN_TERMINAL_STATUS_MAP` `_RUN_STALE_SECONDS` | `runs.py` |
| `_DAEMON_HEALTH_TTL` `_DAEMON_HEALTH_CACHE` `_HOSTING_STATE_TTL` `_HOSTING_STATE_CACHE` `_GLOBAL_BUDGET_CACHE` `_GLOBAL_BUDGET_CACHE_MAX` | `summary.py` |
| `_LIFECYCLE_ORDER` | `timeline.py` |
| `_MANAGED_KEYS` `_AGENTS_MANAGED_SUBKEYS` `_SOURCE_KEYS` `_DEFAULT_SELF_REVIEW` `_CONFIG_HEADER_COMMENT` `_ADMIN_DEFAULTS` `_EFFECTIVE_CONFIG_CACHE` `_EFFECTIVE_CONFIG_CACHE_MAX` `_SYNC_PAGE_KEYS` | `config_admin.py` |
| `EVOLUTION_DOC_WHITELIST` | `evolution_items.py` |

### 4.2 门面保留名（D2/D8）

| 名字 | 理由 |
|---|---|
| `_is_running` | D8：patch 语义；调用点 `daemon_health` 经门面延迟解析 |
| `USER_CONFIG_PATH` | D8：patch 语义；`config_admin.py` 内经门面读取 |
| `_parse_run_task_done` `_find_impl_run_file` | 兼容别名块；同时 re-export 公开名 `find_impl_run_file` `parse_run_task_done` |
| 全部 26 个 import 绑定 | 门面逐条 re-export，保证 `core.dashboard.data.yaml` 等路径可用 |

---

## 5. 「D3 表外但存在于 data.py」的名字

| 名字 | 类型 | 位置线索 | 建议归属 |
|---|---|---|---|
| `run_activity` | 函数 | data.py ~1493（parse_tasks 后，log_index 前） | **runs.py**（读 run 事件存活心跳，与 classify_run/get_runs 同类） |

> 无其他表外函数或常量。32 个常量/别名全部在 D3 表或 §4.0 归属表中有登记。

---

## 6. 测试覆盖状态（供任务 1.2 识别无覆盖函数）

**无测试覆盖的函数（61 个）**——以下函数在 tests/ 目录下无任何 `import` 或属性访问（排除内部别名访问、类定义导出等）：

```
get_alerts get_unhandled_alerts mark_alert_handled mark_all_alerts_handled
get_admin_activities request_admin_invoke request_run_cancel
reclassify_infra_rounds reflow_spec re_review_spec
_write_scheduling_kick_signal set_spec_start_after request_spec_approve_push
set_spec_priority soft_delete_spec is_spec_archived auto_archive_check
find_implementer_worktree _should_overlay _should_overlay?
clear_spec_error _read_spec_scenarios spec_generation_progress
_log_index_path _build_log_block_index _write_log_index
_update_log_block_index _load_log_index _read_log_tail_window
_iter_tail_log_entries _norm_utc_iso _read_log_window_from
parse_report parse_test_scenarios _fold_summary
_load_run_result _run_result_verdict_and_bugs _verdict_from_run_result
_resolve_run_file _first_run_event_ts _read_run_lines _parse_run_lines
get_run_events read_run_events_between active_run_count
_project_summary? _spec_total_duration _resolve_global_impl_run_budget
_stat_sig _runs_by_spec_sigs _spec_dep_sigs _backtrack_reason
_load_billing_config _run_tail_insights _split_llm_marker
_admin_events_for_spec _collapse_timeline _parse_iso_ts _timeline_sort_key
_ts_delta _timeline_with_retry _cost_summary_from_timeline
_degraded_project _token_usage_view _parse_spec_ts _updated_spec_counts
_token_recent_entries _managed_key_sources _managed_admin_keys
_config_file_sig _deep_merge_managed sync_config_from_user
read_evolution_items read_evolution_analysis read_evolution_draft
```

> 注：`clear_spec_error` 在 test_dashboard_api.py 通过 dash_data 访问需再验证；上表需与最终测试扫描交叉核实，此处为保守估算。

# 契约清单：refactor-agent-runner-module

本文件是 `core/agent_runner/runner.py` 的静态清点结果（tasks 1.1），作为拆分重构
的契约基线。锚点一律为**符号名**（design D7：不使用绝对行号锚定验收）。

## 1. 模块级名字清点（runner.py 顶层）

### 1.1 导入名（模块级）

| 名字 | 来源 | 契约地位 |
|---|---|---|
| `json` / `os` / `re` / `shutil` / `sys` / `threading` / `time` / `uuid` / `datetime` / `timezone` / `Path` / `Optional` / `Dict` / `Any` | stdlib | 保留 |
| `subprocess` | stdlib | **D6 补丁缝隙**：测试整体重绑（见 §4） |
| `PromptBuilder` / `planner_result_path` / `planner_result_status_whitelist` / `spec_review_result_path` / `spec_review_result_status_whitelist` | core.agent_runner.prompt_builder | 保留（结果门消费） |
| `AGENT_TERMINATE_GRACE_SECONDS` / `LIVE_ATTEMPT_STREAM_WINDOW_SECONDS` / `SUPERVISION_DEFAULTS` / `JUDGE_TIMEOUT_SECONDS` / `LIVENESS_SNIPPET_CHARS` / `LivenessSupervisor` | core.agent_runner.liveness | 保留 |
| `SessionTracker` | core.agent_runner.session | 保留 |
| `PROVIDER_CIRCUIT_4XX` / `PROVIDER_CIRCUIT_COOLDOWN_SECONDS` / `PROVIDER_CIRCUIT_PROBE_SUCCESS_CODE` / `PROVIDER_CIRCUIT_THRESHOLD` / `PROVIDER_CIRCUIT_WINDOW_SECONDS` / `PROVIDER_DAILY_ATTEMPTS_WARN` / `PROVIDER_SWITCH_COOLDOWN_SECONDS` / `SWITCH_ERROR_CONN_PATTERNS` / `SWITCH_ERROR_TEXT_PATTERNS` / `ProviderCircuit` | core.agent_runner.provider_circuit | 保留 |
| `archive_spec_runs` / `append_run_error` / `append_run_line` / `run_spec_part` | core.agent_runner.run_files | 保留 |
| `TokenAccountant` | core.agent_runner.token_budget | 保留 |
| `V2ServerManager` | core.agent_runner.v2_server | 保留 |
| `find_impl_run_file` / `parse_run_task_done` / `parse_tasks_md` | core.run_task_track | 保留 |
| `V2DevServerError` / `v2_start_dev_server` / `v2_stop_dev_server` / `v2_base_url` / `v2_cleanup_orphans` | core.v2_dev_server | 保留 |
| `ANCHOR_EXTENSION_TAIL` / `ANCHOR_TRANSIENT_BACKOFF` / `ANCHOR_TURN_LIMIT` / `commit_wip_checkpoint` | core.wip_checkpoint | **`commit_wip_checkpoint` 为 D6 补丁缝隙** |

### 1.2 模块级常量

| 名字 | 值 | 契约地位 |
|---|---|---|
| `_ARTIFACT_FRESHNESS_GRACE_SECONDS` | 1.0 | 随消费者迁 `result_gate.py`，经 runner re-export（D2b 规则 3/4） |
| `_PLANREADY_STATUSES` | `("plan-ready",)` | 随消费者迁 `result_gate.py`，经 runner re-export |
| `DEFAULT_GATEWAY_MODEL` | `"claude-sonnet-5"` | 随消费者迁 `maintenance_runs.py`，经 runner re-export |
| `ROUTE_MAP_TIMEOUT_SECONDS` | 60 | 保留（路由地图域） |
| `ROUTE_MAP_REL` / `ROUTE_MAP_HEAD_MARKER_REL` / `ROUTE_MAP_GENERATOR_REL` | 路径常量 | 保留 |
| `FROZEN_TERMINATED_ERROR_PREFIX` / `CANCELLED_BY_ADMIN_ERROR_PREFIX` / `RETRY_YIELDED_ERROR_PREFIX` | 字符串 | 保留 |
| `EXPECTED_SPEC_STATUS_BY_AGENT` / `AGENT_TYPE_TO_ROLE` | dict | 保留 |
| `_PLANNER_SEMAPHORE` | `threading.BoundedSemaphore \| None` | **D6 可 patch 名字**，保留 |
| `_PLANNER_SEMAPHORE_LIMIT` | int | **D6 可 patch 名字**，保留 |
| `_PLANNER_SEMAPHORE_LOCK` | `threading.Lock` | 保留 |
| `THROTTLED_WAIT_HEARTBEAT_SECONDS` | 60.0 | 保留 |
| `ADMIN_DISPOSITION_PREFIX` | `"admin_disposition-"` | 随消费者迁 `maintenance_runs.py` |
| `ADMIN_DISPOSITION_GLOB` | `"admin_disposition-*.json"` | 随消费者迁 `maintenance_runs.py` |
| `V2_TEST_PORT_BASE` / `V2_TEST_PORT_RANGE` / `V2_DEV_SERVER_MARKER` | 19000 / 20 / marker | 保留（V2 域） |
| `LATENCY_STALL_SECONDS` | 60.0 | **随迁 `latency.py`**，经 runner re-export（D4 / D2b 规则 3） |
| `TURN_EXTENSION_STEP_FRACTION` / `TURN_EXTENSION_MAX` / `TURN_EXTENSION_WINDOW_SECONDS` / `EXTENSION_TAIL_WINDOW_SECONDS` | 轮次/尾部常量 | 保留（主链路域） |

### 1.3 模块级函数

| 名字 | 行号 | 契约地位 |
|---|---|---|
| `_route_map_head` | 173 | 保留 |
| `ensure_route_map` | 187 | 保留 |
| `admin_disposition_path` | 270 | 随消费者迁 `maintenance_runs.py`，经 runner re-export |
| `iter_events` | 499 | 迁 `latency.py` |
| `_default_ts_parser` | 504 | `latency.py` 自带等价实现 + runner 保留一行委托（D4 修订版） |
| `_entry_is_tool_result` | 509 | 迁 `latency.py` |
| `latency_samples_from_events` | 540 | 迁 `latency.py` |
| `latency_stats` | 577 | 迁 `latency.py` |
| `_percentile` | 599 | 迁 `latency.py` |
| `format_latency_summary` | 610 | 迁 `latency.py` |

### 1.4 模块级类

| 类 | 行号 | 契约地位 |
|---|---|---|
| `RunCancelledError` | 282 | 迁 `result_gate.py`，经 runner re-export（D6） |
| `AgentArtifactGateError` | 298 | 迁 `result_gate.py`，经 runner re-export（D6） |
| `AgentRunResult` | 315 | 迁 `result_gate.py`，经 runner re-export（D6；pm_engine 直 import） |
| `AdminDisposition` | 374 | 迁 `result_gate.py`，经 runner re-export（D6） |
| `SelfReviewResult` | 412 | 迁 `result_gate.py`，经 runner re-export（D6） |
| `EvolutionResult` | 438 | 迁 `result_gate.py`，经 runner re-export（D6） |
| `AgentRunner` | 632 | 留在 runner.py（门面） |

## 2. AgentRunner 方法名清单（165 个）

（方法名按定义顺序，锚定符号不锚行号。）

```
__init__  _cancel_requested(get/set)  _cancel_meta(get/set)  _cancel_requested_lock(get/set)
_normalize_run_id  _cancel_is_requested  _cancel_clear  cancel_run  _now
_instant_fail(get/set/del)  run_implementer  run_verifier  run_planner
run_dispute_judge  run_spec_review  _planner_throttle_semaphore  _planner_throttle_acquire
ensure_planner_route_map  run_fast_track  run_repair
run_administrator        # → maintenance_runs.py，AgentRunner 保留一行委托
_clear_admin_disposition  _delete_admin_disposition  _read_admin_disposition   # → maintenance_runs.py
run_self_review           # → maintenance_runs.py
_clear_self_review_out  _delete_self_review_out  _read_self_review_out
_accumulate_self_review_tokens                # → maintenance_runs.py
run_evolution            # → maintenance_runs.py
_delete_evolution_out  _accumulate_evolution_tokens  _get_admin_model   # → maintenance_runs.py
_build_isolated_settings  _ensure_agent_config_dir  _select_chain_candidate
_worktree_path_valid  _check_terminal_no_commit_gate  _classify_terminal_no_commit
_salvage_spec_review_result  _wip_checkpoint_before_backoff  _wip_checkpoint_on_forced_kill
_wip_checkpoint_on_extension_tail  _turn_limit_action  _turn_traffic_active  _execute_agent
_execute_agent_inner  _copyback_verify_progress  _run_claude          # _run_claude 保留（D1）
_denoise_stderr  _parse_transient_backoff_schedule  _parse_event_timestamp  # 保留（D1）
_entry_is_tool_result（静态委托）  _check_daily_limit  _get_agent_model_assignment
_get_config  _effective_run_timeout  _spec_is_frozen  _should_give_up_before_retry
_instant_fail_threshold  _instant_fail_cooldown_after  _instant_fail_cooldown_seconds
_run_was_interrupted  _record_instant_fail  _alert_instant_fail_storm  _reset_instant_fail
_instant_fail_counts  is_instant_fail_cooldown  _read_verify_progress  _prompt_builder
_build_prompt
_check_artifact_json_file        # → result_gate.py
_check_agent_result_artifact     # → result_gate.py
_check_impl_result_artifact      # → result_gate.py
_format_gap_list（静态）          # → result_gate.py
_invalid_completed_ids（静态）    # → result_gate.py
_check_success_completion        # → result_gate.py
_check_partial_consistency       # → result_gate.py
_check_taskupdate_crosscheck     # → result_gate.py
_read_init_tools（静态）          # → result_gate.py
_append_crosscheck_skipped       # → result_gate.py
_build_legacy_section  _legacy_dirty_snapshot  _scenario_freeze_section
_interaction_contract_section  _triage_recheck_section  _verdict_rejection_section
_provider_circuit(get)  _token_accountant(get)  _v2_server(get)
parse_api_error_status（静态）  classify_switch_error  classify_transient_error
_circuit_state  is_circuit_open  is_switch_cooldown  _record_switch_cooldown
_write_provider_marker  _record_daily_provider_attempt  _circuit_open_error
_record_provider_4xx  _record_provider_probe  record_transient_break
is_global_transient_break_active  _accumulate_token_usage  _check_token_budget
_send_token_alert  _record_verify_progress_tokens  _v2_ensure_state
_v2_launch_for_worktree  _v2_inject_env  _v2_stop_for_worktree  _v2_harvest_used_worktrees
_v2_stop_all
provider_circuits(get/set/del)  _daily_provider_attempts(get/set/del)
_daily_provider_warned(get/set/del)  _daily_reset_date(get/set/del)
_v2_servers(get/set/del)  _v2_used_ports(get/set/del)  _v2_run_seq(get/set/del)  # 8 组转发属性
_liveness(get)  _session(get)  has_live_attempt  sweep_dangling_runs  _pgrep_live_attempt
_stream_recent  note_run_extension  get_extension_baseline  _liveness_snapshot
_summarize_snapshot  _judge_liveness  _parse_verdict_json  _supervision_settings
_supervision_judge_timeout  _supervision_deadline_action  wait_for_running_agents
running_run_ids  drain_wait  _resumable_session_id  _extract_session_id  _extract_usage_info
_extension_baselines(get/set/del)  # 第 8 组转发属性（对应 _liveness）
```

> 注意：`_IMPL_RESULT_STATUSES` 是 **AgentRunner 类属性**（`("success", "error",
> "partial")`），不是模块级名字。D2b 规则 1 要求产物门函数以 `runner` 参数接收它。

## 3. 提取目标映射

| 新模块 | 迁入符号 | runner 侧处置 |
|---|---|---|
| `result_gate.py` | `RunCancelledError` / `AgentArtifactGateError` / `AgentRunResult` / `AdminDisposition` / `SelfReviewResult` / `EvolutionResult`；`_check_artifact_json_file` / `_check_agent_result_artifact` / `_check_impl_result_artifact` / `_check_success_completion` / `_check_partial_consistency` / `_check_taskupdate_crosscheck` / `_format_gap_list` / `_invalid_completed_ids` / `_read_init_tools` / `_append_crosscheck_skipped`；常量 `_ARTIFACT_FRESHNESS_GRACE_SECONDS` / `_PLANREADY_STATUSES` | re-export + AgentRunner 同名方法一行委托 |
| `maintenance_runs.py` | `run_administrator` / `_clear_admin_disposition` / `_delete_admin_disposition` / `_read_admin_disposition` / `run_self_review` / `_clear_self_review_out` / `_delete_self_review_out` / `_read_self_review_out` / `_accumulate_self_review_tokens` / `run_evolution` / `_delete_evolution_out` / `_accumulate_evolution_tokens` / `_get_admin_model`；常量 `DEFAULT_GATEWAY_MODEL` / `ADMIN_DISPOSITION_PREFIX` / `ADMIN_DISPOSITION_GLOB`；函数 `admin_disposition_path` | re-export + AgentRunner 同名方法一行委托 |
| `latency.py` | `iter_events` / `_default_ts_parser`（等价实现）/ `_entry_is_tool_result` / `latency_samples_from_events` / `latency_stats` / `_percentile` / `format_latency_summary`；常量 `LATENCY_STALL_SECONDS` | re-export + `_default_ts_parser` 模块级一行委托 |

门面依赖注入规则（D2b 规则 1）：产物门函数与维护型 run 函数以 `runner`（AgentRunner
实例）为显式参数接收 `logger` / `project_root` / `_get_config` / `_IMPL_RESULT_STATUSES`
等依赖；新模块 MUST NOT `import runner`。

内部调用点规则（D2b 规则 2）：`runner.py` 内对提取方法的调用 MUST 保持
`self.<方法名>(...)` 形式，MUST NOT 直呼新模块函数。已知打桩依赖点：
`tests/test_worktree_reuse.py:194`、`tests/test_provider_circuit.py:50`、
`tests/test_review_circuit_breaker.py:360`、`tests/test_run_lifecycle_hardening.py:742`、
`tests/test_provider_failover.py:86`（均以 `runner._check_agent_result_artifact =
MagicMock(...)` 在运行期替换行为）。

## 4. D6 补丁缝隙清单（拆分后 MUST 仍可从 `core.agent_runner.runner` 访问且同一路径 patch 命中）

| 名字 | 类型 | 消费方 |
|---|---|---|
| `subprocess` | 模块全局 | `tests/test_fast_track_scale_precheck.py:459-470`、`tests/test_turn_limit_lifecycle.py:182-217`、`tests/test_run_cancel.py`（`runner_module.subprocess.Popen` 替换，:175/:185/:249/:259）整体重绑 |
| `commit_wip_checkpoint` | 模块级导入名 | `tests/test_fast_track_scale_precheck.py:380`、`tests/test_impl_wip_checkpoint.py:602-607` name patch |
| `LATENCY_STALL_SECONDS` | 模块级常量 | `tests/test_run_latency_stats.py:22-29` 导入 |
| `_PLANNER_SEMAPHORE` / `_PLANNER_SEMAPHORE_LIMIT` | 模块级变量 | 既有测试导入/读写 |
| `AgentRunResult` 等结果类 | 类 | `core/pm_engine/spec_review.py:21`、`core/pm_engine/verification.py:4238` 直接 `from core.agent_runner.runner import AgentRunResult` |
| `_ARTIFACT_FRESHNESS_GRACE_SECONDS` / `_PLANREADY_STATUSES` / `DEFAULT_GATEWAY_MODEL` / `admin_disposition_path` | 随迁常量/函数 | `tests/test_admin.py:21`、`tests/test_admin_disposition_failure_context.py:11`（`admin_disposition_path`）；`bin/analyze_run_latency.py:33-35`（latency 名） |

## 5. 测试缝转发属性（D5：8 组，setter/deleter 删除、getter 保留惰性）

| 转发名 | 组合对象 | 测试赋值点（11 文件，MUST 改） |
|---|---|---|
| `provider_circuits` | `_provider_circuit` | helpers.py:125 / test_agent_runner_gate.py:47 / test_planready_artifact_gate.py:40 / test_worktree_reuse.py:182 / test_verdict_contamination.py:455 / test_run_lifecycle_hardening.py:449 / test_transient_backoff.py:432 / test_provider_failover.py:77 / test_retry_orphan_active_runs.py:40 / test_run_cancel.py:63 / test_verdict_dedup_resynthesis.py:518 |
| `_daily_provider_attempts` | `_provider_circuit` | helpers.py:123 / test_agent_runner_gate.py:45 / test_planready_artifact_gate.py:38 / test_worktree_reuse.py:180 / test_verdict_contamination.py:453 / test_transient_backoff.py:430 / test_provider_failover.py:75 / test_retry_orphan_active_runs.py:38 / test_run_cancel.py:61 / test_verdict_dedup_resynthesis.py:516 |
| `_daily_provider_warned` | `_provider_circuit` | helpers.py:124 / test_agent_runner_gate.py:46 / test_planready_artifact_gate.py:39 / test_worktree_reuse.py:181 / test_verdict_contamination.py:454 / test_transient_backoff.py:431 / test_provider_failover.py:76 / test_retry_orphan_active_runs.py:39 / test_run_cancel.py:62 / test_verdict_dedup_resynthesis.py:517 |
| `_daily_reset_date` | `_provider_circuit` | helpers.py:122 / test_agent_runner_gate.py:44 / test_planready_artifact_gate.py:37 / test_worktree_reuse.py:179 / test_verdict_contamination.py:452 / test_run_lifecycle_hardening.py:275 / test_transient_backoff.py:429 / test_provider_failover.py:74 / test_retry_orphan_active_runs.py:37 / test_run_cancel.py:60 / test_verdict_dedup_resynthesis.py:515 |
| `_v2_servers` | `_v2_server` | （测试无赋值点，仅删 setter/deleter） |
| `_v2_used_ports` | `_v2_server` | （同上） |
| `_v2_run_seq` | `_v2_server` | （同上） |
| `_extension_baselines` | `_liveness` | `test_run_lifecycle_governance.py:690` 已直写组合对象（`runner._liveness._extension_baselines`），无需改 |

> 生产内部写点（tasks 4.1，D5 评审补充）：`_check_daily_limit` 内
> `self._daily_reset_date = today` MUST 改为 `self._provider_circuit._daily_reset_date =
> today`，否则 setter 删除后每日额度重置主链路抛 `AttributeError`。

## 6. 行数基线

- 重构前 `runner.py`：5094 行（实测 `wc -l`，2026-09-16 于
  impl-refactor-agent-runner-module-1789512733 worktree）。
- 收敛目标：≤ 3800 行（spec「runner 显著收敛」阈值，可提取量约 1300 行）。
- `AgentRunner` 方法数：165（拆分后方法数减少，但不以方法数为验收）。

## 7. 阶段 0 基线失败集合（tasks 1.4，`bin/run_full_suite.py --timeout 900 --baseline HEAD`）

2026-09-16 实测（当前 worktree 与 HEAD 基线 temp worktree 各跑一次全量套件，
约 151s/次，无挂起）。分类：**存量**（当前失败 ⊆ 基线失败）。

| 测试 | 现状 | 根因（排查） |
|---|---|---|
| `test_dashboard_api.py::TestServerAPI::test_index_served` | 存量失败 | 环境（dashboard 静态产物/dist 缺失，与本次重构无关） |
| `test_dashboard_api.py::TestServerAPI::test_static_root_fallback_to_dist` | 存量失败 | 同上 |
| `test_task_track.py::TestCliWarning::test_missing_tasks_md_silent` | 存量失败 | 环境（temp worktree 内 CLI 子进程 `ModuleNotFoundError: No module named 'core'`，PYTHONPATH 未透传） |
| `test_task_track.py::TestCliWarning::test_parseable_tasks_md_no_warning` | 存量失败 | 同上 |
| `test_task_track.py::TestCliWarning::test_undotted_format_still_parses` | 存量失败 | 同上 |
| `test_task_track.py::TestCliWarning::test_unparseable_tasks_md_prints_warning` | 存量失败 | 同上 |
| `test_callsite_arity_guard.py::TestArityGuardTeeth::test_node_modules_vendored_excluded` | 基线失败、当前通过 | 环境差异（node_modules 存在性随 worktree 变化；flaky） |

验收判据：重构完成后失败集合 MUST 仍 ⊆ 上述基线集合（`--baseline HEAD` 分类为
「存量」或「pass」）。

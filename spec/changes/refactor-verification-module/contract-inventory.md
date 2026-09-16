# 契约清单：refactor-verification-module

本文件是 `core/pm_engine/verification.py`（6304 行）的静态清点结果（tasks 1.1），
作为拆分重构的契约基线。锚点一律为**符号名**（design D6：不使用绝对行号锚定验收）。

## 1. 模块级名字清点（verification.py 顶层）

### 1.1 导入名（模块级）

| 名字 | 来源 | 契约地位 |
|---|---|---|
| `Path` | pathlib | 保留 |
| `Optional` | typing | 保留 |
| `datetime`, `timezone` | datetime | 保留 |
| `json`, `os`, `re`, `subprocess`, `tempfile`, `time`, `urllib.request` | stdlib | 保留；**`subprocess` 为 D9 patch 缝隙**（见 §4） |
| `ServingRegistry` | core.serving_registry | 保留（serving 域） |
| `find_free_port` | core.proc_utils | 保留（serving 域） |
| `CommandVerifyServer`, `StaticVerifyServer` | core.verify_contract | 保留 |
| `ensure_main_tree_deps`, `run_prepare_steps`, `load_verify_contract`, `rewrite_scenarios_origin` | core.verify_contract | **D9 patch 缝隙**：测试以字符串路径 patch（见 §4） |
| `entry_preflight_error`, `probe_ready`, `provision_worktree_node_modules`, `resolve_deps_mode` | core.verify_contract | 保留 |
| `planner_result_status_whitelist` | core.agent_runner.prompt_builder | 保留（verdict 域） |
| `FROZEN_TERMINATED_ERROR_PREFIX` | core.agent_runner.runner | 保留（verdict 域） |
| `ENV_BLOCK_ROUNDS_FIELD`, `FREEZE_ERROR_PREFIX`, `INFRA_FAILURE_COUNT_FIELD`, `VERIFY_INFRA_ROUNDS_FIELD`, `INFRA_REFUNDED_RUN_IDS_FIELD` | core.state_machine | 保留 |

### 1.2 模块级常量

| 名字 | 值 | 契约地位 |
|---|---|---|
| `_SCENARIO_REPAIR_MAX_ROUNDS` | `2` | 保留在 `__init__` re-export（设计 D2 分组表未归属→门面保留） |
| `_MAX_JUDGE_RERUNS` | `5` | 保留在 `__init__` re-export（设计 D2 分组表未归属→门面保留） |
| `RECLASSIFY_SIGNAL_TYPE` | `"infra_reclassify"` | 迁 `infra_classify.py`，经 `__init__` re-export |
| `POST_READY_SETTLE_SECONDS` | `10` | 迁 `serving.py`，经 `__init__` re-export |
| `LEGACY_START_PROBE_ATTEMPTS` | `30` | 迁 `legacy.py`，经 `__init__` re-export |
| `LEGACY_START_PROBE_INTERVAL_SECONDS` | `1` | 迁 `legacy.py`，经 `__init__` re-export |
| `ENV_BLOCK_SIGNAL_TYPES` | `("verify_env_blocked", "verify_env_inconclusive")` | 保留在 `__init__` re-export（被门面 `resolve_env_blocked_reset_path` 引用） |
| `ENV_BLOCK_MERGE_CHECK_TIMEOUT_SECONDS` | `10` | 保留在 `__init__` re-export（被 `_branch_merged_into_tree` 引用） |

### 1.3 模块级类

| 类 | 契约地位 |
|---|---|
| `VerdictReadResult` | 迁 `report_gate.py`，经 `__init__` re-export（15+ 测试文件 `from ... import VerdictReadResult`） |
| `VerificationPipeline` | 门面组装类，最终归 `pipeline.py`，经 `__init__` re-export |

### 1.4 模块级函数

| 名字 | 契约地位 |
|---|---|
| `resolve_env_blocked_reset_path(spec, project_root)` | 保留在 `__init__`（被门面 `engine.py` 及 `admin_monitor` import） |
| `_branch_merged_into_tree(branch, project_root)` | 迁 `branch_guard.py`，经 `__init__` re-export（被 `resolve_env_blocked_reset_path` 调用；`test_pm_verification.py:1907` import） |
| `reclassify_infra_rounds(...)` | 迁 `infra_classify.py`，经 `__init__` re-export（被 `engine.py:2659` import） |

## 2. VerdictReadResult 方法清单（5 个）

| 方法名 | 可见性 | 说明 |
|---|---|---|
| `__init__(self, status=None, reason="", detail="")` | 公共 | 三态构造 |
| `ok` (property) | 公共 | `status is not None` |
| `success(cls, status)` | 公共（classmethod） | 成功构造 |
| `failure(cls, reason, detail)` | 公共（classmethod） | 失败构造 |
| `__repr__(self)` | 公共 | 表示字符串 |

> `__slots__ = ("status", "reason", "detail")`。

## 3. VerificationPipeline 方法名清单（92 个）

（方法名按定义顺序，锚定符号不锚行号。`_run_three_stage_verification` 为 1165 行大函数，内部逻辑不动。）

```
__init__                                    # D10：接收 pm，存 self._pm
_read_verify_report                         # → report_gate.py
_handle_env_blocked_inconclusive            # → escalation.py
_write_inconclusive_loop_signal             # → escalation.py
_speculative_bug_found_gate                 # → escalation.py
_serve_static_in_main                       # → serving.py
_ensure_serving_worktree                    # → serving.py
_serve_static_in_worktree                   # → serving.py
_port_responds                              # → serving.py（静态方法）
_serve_command_in_worktree                  # → serving.py
_serve_command_in_main                      # → serving.py
_finalize_static                            # → serving.py
_remove_serving_worktree                    # → serving.py
_register_serving_instance                  # → serving.py
_unregister_serving_instance                # → serving.py
_evict_spec_serving                         # → serving.py
_current_instance_base_url                  # → serving.py
_ensure_app_reachable                       # → serving.py
_open_boot_log                              # → serving.py
_read_boot_log_tail                         # → serving.py
_write_verify_contract_missing              # → scenario_gate.py
_rewrite_scenario_port                      # → serving.py
_current_verify_round                       # → serving.py
_serving_port_for_spec                      # → serving.py
_run_scenario_static_check                  # → scenario_gate.py
_run_contract_static_check                  # → scenario_gate.py
_apply_scenario_freeze                      # → scenario_gate.py
_apply_interaction_contract                 # → scenario_gate.py
_render_scenario_change_section_to_report   # → scenario_gate.py
_run_three_stage_verification               # → pipeline.py（整体搬移，1165 行）
_verifier_error_is_infra                    # → infra_classify.py
enrich_failure_class                        # → infra_classify.py（公共）
_record_infra_failure                       # → infra_classify.py
_verifier_result_is_stale                   # → report_gate.py
_branch_commit_count                        # → branch_guard.py
_implementation_branch_has_commits          # → branch_guard.py
_implementer_zero_change                    # → branch_guard.py
_deliverable_gate_missing                   # → branch_guard.py
_tasks_md_relint_from_branch                # → branch_guard.py
_tasks_md_relint_from_worktree              # → branch_guard.py
_disputed_deliverables                      # → branch_guard.py
_normalize_fail_signature                   # → infra_classify.py（静态方法）
_extract_replan_error_items                 # → branch_guard.py（静态方法）
_replan_errors_unconsumed                   # → branch_guard.py（静态方法）
_detect_uniform_verify_failure              # → infra_classify.py
_run_legacy_verification                    # → legacy.py
_load_frozen_scenarios                      # → scenario_gate.py（静态方法）
_env_whitewash_gate                         # → escalation.py
_escalate_env_blocked                       # → escalation.py
_last_planner_cost_usd                      # → judge_gate.py
_write_degrade_context                      # → judge_gate.py
_clear_degrade_context                      # → judge_gate.py
_last_planner_run_cost                      # → judge_gate.py
_all_green_fast_path                        # → judge_gate.py
_judge_rerun_count                          # → judge_gate.py
_judge_dispatch_gate                        # → judge_gate.py
_judge_hard_cap_freeze                      # → judge_gate.py
_verified_verdict_persisted                 # → verdict_evidence.py
_verified_gate_refuses                      # → verdict_evidence.py
_record_verdict_adoption                    # → verdict_evidence.py
_persist_verdict_cache                      # → verdict_evidence.py
_verdict_violations_evidence                # → verdict_evidence.py
_resynthesis_directive_path                 # → verdict_evidence.py
_read_resynthesis_directive                 # → verdict_evidence.py
_clear_resynthesis_directive                # → verdict_evidence.py
_clear_requeue_manifest                     # → verdict_evidence.py
_resynthesis_directive_scenarios            # → verdict_evidence.py
_write_resynthesis_directive                # → verdict_evidence.py
_escalate_dedup_resynthesis                 # → verdict_evidence.py
_handle_attr_dedup_rejection                # → verdict_evidence.py
_handle_scenario_requeue                    # → verdict_evidence.py
_verify_verdict_evidence                    # → verdict_evidence.py
_fail_history_path                          # → infra_classify.py
_read_fail_history                          # → infra_classify.py
_append_fail_history                        # → infra_classify.py
_clear_fail_history                         # → infra_classify.py
_failed_scenario_ids                        # → infra_classify.py
_scenario_classification_distribution       # → infra_classify.py
_scenario_defect_reroute_gate               # → escalation.py
_escalate_scenario_defect_reroute           # → escalation.py
_update_warning_streaks                     # → escalation.py
_warning_stale_triage_alert                 # → escalation.py
_ensure_verification_report                 # → report_gate.py
_check_verification_gate                    # → report_gate.py
_read_verifier_result                       # → report_gate.py
_read_planner_result                        # → report_gate.py
_read_verdict                               # → report_gate.py
_judge_bugs_declare_env                     # → escalation.py
_handle_judge_env_declared                  # → escalation.py
_verdict_violations_path                    # → verdict_evidence.py
_write_verdict_violations                   # → verdict_evidence.py
_clear_verdict_violations                   # → verdict_evidence.py
```

## 3.1 实例属性（非方法，但跨组件读取）

| 属性名 | 写入方法 | 读取方式 | 契约地位 |
|---|---|---|---|
| `_last_scenario_diff` | `_apply_scenario_freeze` | `engine.py` 经 `self._verification._last_scenario_diff`（property-like 访问） | 随 `scenario_gate.py` 迁移，`pipeline.py` 暴露为只读 property |
| `_last_interaction_contract` | `_apply_interaction_contract` | `engine.py` 经 `self._verification._last_interaction_contract` | 同上 |

## 4. D9 patch 缝隙清单（拆分后 MUST 仍可从 `core.pm_engine.verification` 访问且同一路径 patch 命中）

| 名字 | 类型 | 消费方 |
|---|---|---|
| `subprocess` | 模块级 import | `tests/test_blocked_reverify_gate.py`（11 处 `core.pm_engine.verification.subprocess.run`）、`tests/test_frozen_scenario_schema_migration.py`（3 处）——整体重绑 |
| `ensure_main_tree_deps` | 模块级 import（core.verify_contract） | `tests/test_main_tree_deps_provision.py:172,203` patch |
| `run_prepare_steps` | 模块级 import（core.verify_contract） | `tests/test_main_tree_deps_provision.py:173,204` patch |
| `load_verify_contract` | 模块级 import（core.verify_contract） | `tests/test_main_tree_deps_provision.py:189,218` patch |
| `rewrite_scenarios_origin` | 模块级 import（core.verify_contract） | `tests/test_verify_command_port.py:287` patch |

**保持规则（D8/D9）**：包 `__init__` MUST 保留上述 5 个名字的引用；子模块中的调用点经包命名空间延迟解析，使 `patch("core.pm_engine.verification.<name>")` 继续命中。阶段 3 每组搬移后 MUST 复跑这 4 个测试文件。

## 5. 测试引用清点（24 个测试文件 import verification 模块）

### 5.1 公开符号 import 路径（`from core.pm_engine.verification import ...`）

| 测试文件 | 导入的符号 |
|---|---|
| `test_pm_verification.py` | `VerdictReadResult`, `_SCENARIO_REPAIR_MAX_ROUNDS`, `_branch_merged_into_tree` |
| `test_blocked_reverify_gate.py` | `VerificationPipeline` 等（具体见文件） |
| `test_frozen_scenario_schema_migration.py` | `VerificationPipeline` 等 |
| `test_frozen_scenario_reservoir.py` | `VerificationPipeline` |
| `test_planner_scenario_schema_alignment.py` | `VerdictReadResult`, `VerificationPipeline` |
| `test_scenario_reroute_gate.py` | `VerificationPipeline` 等 |
| `test_verdict_evidence_taxonomy.py` | `VerificationPipeline` |
| `test_verdict_contamination.py` | `VerdictReadResult` |
| `test_verdict_read_failclosed.py` | `VerdictReadResult` |
| `test_verdict_stability.py` | `_MAX_JUDGE_RERUNS` |
| `test_pm_recovery.py` | `VerdictReadResult` |
| `test_infra_budget_exempt.py` | `VerdictReadResult` |
| `test_judge_efficiency.py` | `VerificationPipeline` |
| `test_fasttrack_orphan_planner_race.py` | `VerdictReadResult` |
| `test_verify_parallel_backoff.py` | `VerdictReadResult` |
| `test_planready_artifact_gate.py` | `VerdictReadResult` |
| `test_main_tree_deps_provision.py` | `VerificationPipeline`（构造签名） |
| `fixtures/schema-alignment-showcase/check.py` | `VerificationPipeline`（构造签名，4 处） |

> `test_pm_verification.py:586` 以 `from core.pm_engine.verification import _SCENARIO_REPAIR_MAX_ROUNDS` 直接访问常量；
> `:1907` 以 `from core.pm_engine.verification import _branch_merged_into_tree` 直接访问模块级函数。
> 这些 MUST 在 `__init__` re-export 后仍可导入。

## 6. self._pm.* 回引清单（495 处）

### 6.1 公共回引（404 处，5 个目标）

| 目标 | 调用次数 | D1 context 归属 | 分阶段 |
|---|---|---|---|
| `self._pm.logger` | 207 | `context.logger` | 阶段 2 替换 |
| `self._pm.project_root` | 99 | `context.project_root` | 阶段 2 替换 |
| `self._pm.state_machine` | 87 | `context.state_machine` | 阶段 2 替换 |
| `self._pm.agent_runner` | 10 | 待定（D10 未给成员） | 阶段 1 补齐 context |
| `self._pm.config` | 1 | 待定（D10 未给成员） | 阶段 1 补齐 context |

### 6.2 私有回引（91 处，40 个不同目标）

**A. PMEngine 私有目标（9 个，34 处调用）——D1 必须由 PipelineContext 补齐：**

| 目标 | 调用次数 | 建议 context 成员名 |
|---|---|---|
| `self._pm._send_human_escalation_alert` | 11 | `escalation_notifier`（委托原方法） |
| `self._pm._get_config` | 11 | `config_reader`（委托原方法） |
| `self._pm._enqueue` | 3 | `enqueue`（委托原方法） |
| `self._pm._is_fix_spec` | 2 | `is_fix_spec`（委托原方法） |
| `self._pm._on_spec_verified` | 2 | `on_spec_verified`（委托原方法） |
| `self._pm._on_spec_bug_found` | 2 | `on_spec_bug_found`（委托原方法） |
| `self._pm._read_implementer_result` | 1 | `read_implementer_result`（委托原方法） |
| `self._pm._exempt_infra_run_budget` | 1 | `exempt_infra_run_budget`（委托原方法） |
| `self._pm._ENV_INFRA_MARKERS` | 1 | `env_infra_markers`（只读属性） |

**B. 自身方法绕行回引（31 个目标，57 处调用）——阶段 1 替换为组件间直连：**

| 目标 | 调用次数 | 目标子模块（D2 归组） |
|---|---|---|
| `_read_verifier_result` | 4 | report_gate |
| `_read_verdict` | 4 | report_gate |
| `_ensure_verification_report` | 4 | report_gate |
| `_env_whitewash_gate` | 3 | escalation |
| `_clear_verdict_violations` | 3 | verdict_evidence |
| `_apply_scenario_freeze` | 3 | scenario_gate |
| `_write_verdict_violations` | 2 | verdict_evidence |
| `_verifier_result_is_stale` | 2 | report_gate |
| `_verifier_error_is_infra` | 2 | infra_classify |
| `_verdict_violations_path` | 2 | verdict_evidence |
| `_speculative_bug_found_gate` | 2 | escalation |
| `_rewrite_scenario_port` | 2 | serving |
| `_render_scenario_change_section_to_report` | 2 | scenario_gate |
| `_handle_env_blocked_inconclusive` | 2 | escalation |
| `_clear_fail_history` | 2 | infra_classify |
| `_check_verification_gate` | 2 | report_gate |
| `_apply_interaction_contract` | 2 | scenario_gate |
| `_warning_stale_triage_alert` | 1 | escalation |
| `_verify_verdict_evidence` | 1 | verdict_evidence |
| `_update_warning_streaks` | 1 | escalation |
| `_scenario_defect_reroute_gate` | 1 | escalation |
| `_run_scenario_static_check` | 1 | scenario_gate |
| `_read_verify_report` | 1 | report_gate |
| `_read_planner_result` | 1 | report_gate |
| `_normalize_fail_signature` | 1 | infra_classify |
| `_judge_bugs_declare_env` | 1 | escalation |
| `_handle_judge_env_declared` | 1 | escalation |
| `_ensure_app_reachable` | 1 | serving |
| `_detect_uniform_verify_failure` | 1 | infra_classify |
| `_current_verify_round` | 1 | serving |
| `_append_fail_history` | 1 | infra_classify |

> 合计 B：4×3+3×3+2×11+1×14 = 12+9+22+14 = 57 处 ✓

## 7. engine.py 门面委托清点（44 个委托方法）

`core/pm_engine/engine.py` 以 `return self._verification._<method>(...)` 形式委托到 VerificationPipeline，
其中包含 2 个属性访问（`_last_scenario_diff` / `_last_interaction_contract`）和 42 个方法委托。
本变更**MUST NOT 修改委托方法体**，仅可适配 import 行与 `_verification` property 的构造方式。

## 8. 行数基线

- 重构前 `verification.py`：6304 行（`wc -l` 实测）。
- `_run_three_stage_verification`：1165 行（整体搬移，内部不拆）。
- `VerificationPipeline` 方法数：92（加上 `VerdictReadResult` 的 5 个，共 97）。

## 9. 方法总数汇总（D2 分组覆盖清单）

全部 92 个 VerificationPipeline 方法在 D2 分组表中的归属：

| 目标子模块 | 迁入方法数 | 方法名 |
|---|---|---|
| `pipeline.py` | 2 | `__init__`, `_run_three_stage_verification` |
| `serving.py` | 18 | `_ensure_serving_worktree`, `_serve_static_in_main`, `_serve_static_in_worktree`, `_serve_command_in_worktree`, `_serve_command_in_main`, `_finalize_static`, `_remove_serving_worktree`, `_register_serving_instance`, `_unregister_serving_instance`, `_evict_spec_serving`, `_current_instance_base_url`, `_ensure_app_reachable`, `_port_responds`, `_open_boot_log`, `_read_boot_log_tail`, `_rewrite_scenario_port`, `_serving_port_for_spec`, `_current_verify_round` |
| `scenario_gate.py` | 7 | `_write_verify_contract_missing`, `_run_scenario_static_check`, `_run_contract_static_check`, `_apply_scenario_freeze`, `_apply_interaction_contract`, `_render_scenario_change_section_to_report`, `_load_frozen_scenarios` |
| `verdict_evidence.py` | 18 | `_verified_verdict_persisted`, `_verified_gate_refuses`, `_record_verdict_adoption`, `_persist_verdict_cache`, `_verdict_violations_evidence`, `_verify_verdict_evidence`, `_verdict_violations_path`, `_write_verdict_violations`, `_clear_verdict_violations`, `_resynthesis_directive_path`, `_read_resynthesis_directive`, `_clear_resynthesis_directive`, `_resynthesis_directive_scenarios`, `_write_resynthesis_directive`, `_escalate_dedup_resynthesis`, `_handle_attr_dedup_rejection`, `_handle_scenario_requeue`, `_clear_requeue_manifest` |
| `judge_gate.py` | 8 | `_last_planner_cost_usd`, `_last_planner_run_cost`, `_write_degrade_context`, `_clear_degrade_context`, `_all_green_fast_path`, `_judge_rerun_count`, `_judge_dispatch_gate`, `_judge_hard_cap_freeze` |
| `escalation.py` | 11 | `_handle_env_blocked_inconclusive`, `_write_inconclusive_loop_signal`, `_speculative_bug_found_gate`, `_env_whitewash_gate`, `_escalate_env_blocked`, `_scenario_defect_reroute_gate`, `_escalate_scenario_defect_reroute`, `_update_warning_streaks`, `_warning_stale_triage_alert`, `_judge_bugs_declare_env`, `_handle_judge_env_declared` |
| `infra_classify.py` | 11 | `_verifier_error_is_infra`, `enrich_failure_class`, `_record_infra_failure`, `_detect_uniform_verify_failure`, `_normalize_fail_signature`, `_fail_history_path`, `_read_fail_history`, `_append_fail_history`, `_clear_fail_history`, `_failed_scenario_ids`, `_scenario_classification_distribution` |
| `legacy.py` | 1 | `_run_legacy_verification` |
| `branch_guard.py` | 9 | `_branch_commit_count`, `_implementation_branch_has_commits`, `_implementer_zero_change`, `_deliverable_gate_missing`, `_tasks_md_relint_from_branch`, `_tasks_md_relint_from_worktree`, `_disputed_deliverables`, `_extract_replan_error_items`, `_replan_errors_unconsumed` |
| `report_gate.py` | 7 | `_read_verify_report`, `_ensure_verification_report`, `_check_verification_gate`, `_verifier_result_is_stale`, `_read_verifier_result`, `_read_planner_result`, `_read_verdict` |
| **合计** | **92** | — |

> **无未归属项**：全部 92 个方法已逐名落位到 D2 分组表中的目标子模块。

> **读取辅助归属裁决**（tasks 4.2 / 4.11 的交叉）：`_read_verifier_result` /
> `_read_planner_result` / `_read_verdict` 在 design D2 中标注「若仅 legacy 用则随迁」。
> 实测（tasks 1.1 清点）：`_read_verdict` 被 `_run_three_stage_verification`
> （:2596/:2632/:3514/:5501）与 `_run_legacy_verification`（:3507 注释引用）**两侧消费**，
> `_read_planner_result` 亦被主链路（:1947）消费，三者的**仅**归因不成立——
> 故归 `report_gate.py`（读取白名单域），`legacy.py` 仅迁 `_run_legacy_verification`
> 一个方法；执行阶段以本裁决为准，若不采纳另行说明。

## 10. 构造签名兼容基线（tasks 1.8）

`VerificationPipeline(pm)` 位置参数调用点（阶段 1 构造签名 MUST 保持可用，
context 为可选参数或由 pm 内部推导）：

| 调用点 | 形式 |
|---|---|
| `core/pm_engine/engine.py:2697` | `VerificationPipeline(self)`（`_verification` property） |
| `tests/test_scenario_reroute_gate.py:78,143` | `VerificationPipeline(self.pm)` |
| `tests/test_frozen_scenario_reservoir.py:264,280,290,314,336,426,436` | `VerificationPipeline(pm)` |
| `tests/test_main_tree_deps_provision.py:180,210` | `VerificationPipeline(pm)` |
| `tests/test_planner_scenario_schema_alignment.py:387,413,442,473,501,525,552,588,783,847` | `VerificationPipeline(pm)` |
| `tests/fixtures/schema-alignment-showcase/check.py:185,225,266,304` | `VerificationPipeline(pm)` |

> 全部为**单位置参数**调用，无一传递 context 关键字——阶段 1 引入
> `context: PipelineContext | None = None` 可选参数即可全部兼容。

## 11. D2 分组覆盖核对（tasks 1.5）

将 `VerdictReadResult` 的 4 个方法与 resynthesis 族、三项读取辅助逐名落位到
D2 分组表（不留未归属项）：

| 方法 | D2 落位 |
|---|---|
| `VerdictReadResult.ok`（property） | `report_gate.py`（随 `VerdictReadResult` 类） |
| `VerdictReadResult.success`（classmethod） | `report_gate.py`（随类） |
| `VerdictReadResult.failure`（classmethod） | `report_gate.py`（随类） |
| `VerdictReadResult.__repr__` | `report_gate.py`（随类） |
| `_resynthesis_directive_path` | `verdict_evidence.py`（resynthesis 族 1/9） |
| `_read_resynthesis_directive` | `verdict_evidence.py`（2/9） |
| `_clear_resynthesis_directive` | `verdict_evidence.py`（3/9） |
| `_resynthesis_directive_scenarios` | `verdict_evidence.py`（4/9） |
| `_write_resynthesis_directive` | `verdict_evidence.py`（5/9） |
| `_escalate_dedup_resynthesis` | `verdict_evidence.py`（6/9） |
| `_handle_attr_dedup_rejection` | `verdict_evidence.py`（7/9） |
| `_handle_scenario_requeue` | `verdict_evidence.py`（8/9） |
| `_clear_requeue_manifest` | `verdict_evidence.py`（9/9，design D2 列表含此名） |
| `_read_verifier_result` | `report_gate.py`（见 §9 归属裁决） |
| `_read_planner_result` | `report_gate.py`（同上） |
| `_read_verdict` | `report_gate.py`（同上） |

> resynthesis 族为 **9 项**（design D2 以「8 项」概括，实际代码含
> `_clear_requeue_manifest` 共 9 个方法，逐名列上）；无未归属项。
> `VerificationPipeline.__init__` 与 `_run_three_stage_verification` 保留在
> `pipeline.py` 门面。

## 12. 私有回引逐名核对（tasks 1.7）

§6.2 已给出 40 个私有目标的完整清单（9 个 `PMEngine` 私有 + 31 个自身方法
绕行）。经与 `core/pm_engine/engine.py` 逐名比对（`grep -c "def <name>"`），
9 个 `PMEngine` 私有目标全部存在于 engine.py：

| 目标 | engine.py 存在性 | 阶段 1 context 处置 |
|---|---|---|
| `_send_human_escalation_alert` | ✓（def 存在） | `escalation_notifier`（委托原方法） |
| `_get_config` | ✓ | `config_reader`（委托原方法） |
| `_enqueue` | ✓ | `enqueue`（委托原方法） |
| `_is_fix_spec` | ✓ | `is_fix_spec`（委托原方法） |
| `_on_spec_verified` | ✓ | `on_spec_verified`（委托原方法） |
| `_on_spec_bug_found` | ✓ | `on_spec_bug_found`（委托原方法） |
| `_read_implementer_result` | ✓ | `read_implementer_result`（委托原方法） |
| `_exempt_infra_run_budget` | ✓ | `exempt_infra_run_budget`（委托原方法） |
| `_ENV_INFRA_MARKERS` | ✓（常量） | `env_infra_markers`（只读属性） |

> 另有 5 个公共目标（`logger` / `project_root` / `state_machine` /
> `agent_runner` / `config`）为 PMEngine 公共属性，无需「私有回引」处置；
> `agent_runner` 与 `config` 不在 D1 六成员清单中，阶段 1 一并补齐 context
> 成员（见 §6.1 分阶段列）。

## 13. 阶段 0 基线失败集合（tasks 1.4，`bin/run_full_suite.py --timeout 3600 --baseline HEAD`）

2026-09-16 实测（当前 worktree 与 HEAD 基线 temp worktree 各跑一次全量套件，
约 153s/次，无挂起）。分类：**存量**（当前失败 ⊆ 基线失败，无本次引入）。

| 测试 | 现状 | 根因（与 refactor-agent-runner-module 基线一致） |
|---|---|---|
| `test_dashboard_api.py::TestServerAPI::test_index_served` | 存量失败 | 环境（dashboard 静态产物/dist 缺失，与本次重构无关） |
| `test_dashboard_api.py::TestServerAPI::test_static_root_fallback_to_dist` | 存量失败 | 同上 |
| `test_task_track.py::TestCliWarning::test_missing_tasks_md_silent` | 存量失败 | 环境（temp worktree 内 CLI 子进程 `ModuleNotFoundError: No module named 'core'`，PYTHONPATH 未透传） |
| `test_task_track.py::TestCliWarning::test_parseable_tasks_md_no_warning` | 存量失败 | 同上 |
| `test_task_track.py::TestCliWarning::test_undotted_format_still_parses` | 存量失败 | 同上 |
| `test_task_track.py::TestCliWarning::test_unparseable_tasks_md_prints_warning` | 存量失败 | 同上 |
| `test_callsite_arity_guard.py::TestArityGuardTeeth::test_node_modules_vendored_excluded` | 基线失败、当前通过 | 环境差异（node_modules 存在性随 worktree 变化；flaky） |

> 本次新增的 `tests/test_characterization_verification.py`（22 用例）全部通过，
> 未引入新失败。验收判据：重构完成后失败集合 MUST 仍 ⊆ 上述基线集合。

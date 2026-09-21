# Tasks: refactor-verification-module

## Deliverables

```yaml
- path: core/pm_engine/verification/__init__.py
  kind: new
- path: core/pm_engine/verification/pipeline.py
  kind: new
- path: core/pm_engine/verification/serving.py
  kind: new
- path: core/pm_engine/verification/scenario_gate.py
  kind: new
- path: core/pm_engine/verification/verdict_evidence.py
  kind: new
- path: core/pm_engine/verification/judge_gate.py
  kind: new
- path: core/pm_engine/verification/escalation.py
  kind: new
- path: core/pm_engine/verification/infra_classify.py
  kind: new
- path: core/pm_engine/verification/legacy.py
  kind: new
- path: core/pm_engine/verification/branch_guard.py
  kind: new
- path: core/pm_engine/verification/report_gate.py
  kind: new
- path: core/pm_engine/verification/context.py
  kind: new
- path: core/pm_engine/verification.py
  kind: delete
- path: tests/test_characterization_verification.py
  kind: new
- path: tests/test_verification_modules_contract.py
  kind: new
- path: core/pm_engine/engine.py
  kind: modify
- path: spec/changes/refactor-verification-module/contract-inventory.md
  kind: new
- path: spec/changes/refactor-verification-module/verification-findings.md
  kind: new
- path: spec/changes/refactor-verification-module/formatting-report.md
  kind: new
```

> `core/pm_engine/engine.py` 的 `kind: modify` 仅限**组合/导入适配**（`_verification` property 的构造方式、import 行）；
> 其**既有门面委托方法体 MUST NOT 需要修改**（与 spec.md「引擎门面委托保持不变」口径一致）。

## 1. 阶段 0：测试基线加固

- [x] 1.1 静态清点：提取 `VerificationPipeline` 全部方法名与 `self._pm.*` 回引清单（按私有/公共、按目标属性分类），落盘为契约清单（`contract-inventory.md`）
- [x] 1.2 补 characterization tests（`tests/test_characterization_verification.py`）：锁定 `_apply_scenario_freeze`、`_env_whitewash_gate`、`_verified_gate_refuses`、`_record_verdict_adoption`、`_handle_env_blocked_inconclusive`、`_run_scenario_static_check` 等的可观测行为
- [x] 1.3 建立疑点清单（`verification-findings.md`），只记录不修
- [x] 1.4 运行 `bin/run_full_suite.py` 记录基线失败集合（重点 `test_pm_verification` 67 用例、`test_verdict_*`、`test_env_sanity_gate`）
- [x] 1.5 **分组覆盖核对**（design D2）：把 `VerificationPipeline` 全部方法（含 `VerdictReadResult` 的 `ok`/`success`/`failure`/`__repr__`、resynthesis 族 8 项、`_read_verifier_result`/`_read_planner_result`/`_read_verdict`）逐名落位到 D2 分组表，未归属项 MUST 显式归组或标注「保留在门面」，落盘 `contract-inventory.md`，**不留未归属项**
- [x] 1.6 **patch 目标清点**（design D9）：固定 `core.pm_engine.verification.subprocess.run`（`tests/test_blocked_reverify_gate.py` 11 处、`tests/test_frozen_scenario_schema_migration.py` 3 处）、`ensure_main_tree_deps`/`run_prepare_steps`/`load_verify_contract`（`tests/test_main_tree_deps_provision.py` 6 处）、`rewrite_scenarios_origin`（`tests/test_verify_command_port.py:287`）的当前语义基线；无法保持者列入「测试零修改」例外清单待用户裁决
- [x] 1.7 **私有回引清单逐名核对**（design D10）：确认 context 成员与「组件间直连」两类规则合起来覆盖 `self._pm._*` 的**全部 40 个**不同目标（91 处调用点）（含 `_is_fix_spec`/`_on_spec_verified`/`_on_spec_bug_found`/`_read_implementer_result`/`_exempt_infra_run_budget`/`_ENV_INFRA_MARKERS` 这 6 个 `PMEngine` 私有目标）
- [x] 1.8 **构造签名兼容基线**：记录 `VerificationPipeline(pm)` 位置参数调用点（`tests/test_scenario_reroute_gate.py`、`tests/test_frozen_scenario_reservoir.py`、`tests/test_main_tree_deps_provision.py`、`tests/test_planner_scenario_schema_alignment.py`、`tests/fixtures/schema-alignment-showcase/check.py`）与 `core/pm_engine/engine.py:2602`，作为阶段 1 签名不得破坏的清单

## 2. 阶段 1：PipelineContext 引入与私有回引替换

- [x] 2.1 新建 `core/pm_engine/verification/context.py`：定义 `PipelineContext`，成员 `logger` / `project_root` / `state_machine` / `config_reader` / `escalation_notifier` / `enqueue`（后三者以委托原门面方法实现，保证语义一致）
- [x] 2.2 在原 `verification.py` 内让 `VerificationPipeline` 构造接收 context：签名 MUST 保持 `VerificationPipeline(pm)` 位置调用可用（context 为可选参数或由 `pm` 内部推导），MUST NOT 破坏任务 1.8 清单中的既有构造调用点；替换全部 `self._pm._send_human_escalation_alert` / `self._pm._get_config` / `self._pm._enqueue` 等**门面私有**回引，并按 D10 补齐 `_is_fix_spec` / `_on_spec_verified` / `_on_spec_bug_found` / `_read_implementer_result` / `_exempt_infra_run_budget` / `_ENV_INFRA_MARKERS` 的 context 成员
- [x] 2.3 替换 `self._pm._<自身方法>` 类绕行回引为组件间直连（约 30 个目标，按任务 1.7 清单逐名核对）
- [x] 2.4 全量 pytest（重点验证/裁决/env 用例），独立 commit

## 3. 阶段 2：公共只读依赖回引替换

- [x] 3.1 替换 `self._pm.logger` / `self._pm.project_root` / `self._pm.state_machine` 为 context 访问
- [x] 3.2 校验 `grep "self\._pm\._"` 在 `verification.py` 中为 0；全量 pytest，独立 commit

## 4. 阶段 3：分组搬移

- [x] 4.1 **先改名入包**（design D8）：`core/pm_engine/verification.py` → `core/pm_engine/verification/_legacy.py`，新建 `__init__.py` 以显式名单 re-export `_legacy` 的全部既有公开与私有名字（含 `VerificationPipeline`、`VerdictReadResult`、`reclassify_infra_rounds`、`resolve_env_blocked_reset_path`、`_branch_merged_into_tree`、`_SCENARIO_REPAIR_MAX_ROUNDS`、`_MAX_JUDGE_RERUNS` 等）；本步 MUST 全量回归全绿后独立 commit。**禁止**在旧 `verification.py` 仍存在时先建同名包目录（同名包会遮蔽模块，导致全部 import 瞬时失效）
- [x] 4.1b 按 D9 落实 patch 语义保持：包 `__init__` 保留 `subprocess` / `ensure_main_tree_deps` / `run_prepare_steps` / `load_verify_contract` / `rewrite_scenarios_origin` / `probe_ready` / `time` 引用，子模块调用点经包命名空间延迟解析；复跑 `test_blocked_reverify_gate.py`、`test_frozen_scenario_schema_migration.py`、`test_main_tree_deps_provision.py`、`test_verify_command_port.py`
- [x] 4.2 搬 `report_gate.py`：`_read_verify_report` / `_ensure_verification_report` / `_check_verification_gate` / `_verifier_result_is_stale` / `VerdictReadResult`
- [x] 4.3 搬 `branch_guard.py`：`_implementation_branch_has_commits` / `_branch_commit_count` / `_implementer_zero_change` / `_deliverable_gate_missing` / `_tasks_md_relint_from_branch` / `_tasks_md_relint_from_worktree` / `_disputed_deliverables` / `_extract_replan_error_items` / `_replan_errors_unconsumed` / `resolve_env_blocked_reset_path` / `_branch_merged_into_tree`
- [x] 4.4 搬 `infra_classify.py`：`_verifier_error_is_infra` / `enrich_failure_class` / `_record_infra_failure` / `_detect_uniform_verify_failure` / `reclassify_infra_rounds` / `_fail_history_path` / `_read_fail_history` / `_append_fail_history` / `_clear_fail_history` / `_scenario_classification_distribution` / `_failed_scenario_ids` / `_normalize_fail_signature`
- [x] 4.5 搬 `scenario_gate.py`：`_apply_scenario_freeze` / `_apply_interaction_contract` / `_load_frozen_scenarios` / `_render_scenario_change_section_to_report` / `_write_verify_contract_missing` / `_run_scenario_static_check` / `_run_contract_static_check`
- [x] 4.6 门面 re-export 本组符号；全量 pytest + import 校验，独立 commit
- [x] 4.7 搬 `serving.py`：`_ensure_serving_worktree` / `_serve_static_in_main` / `_serve_static_in_worktree` / `_serve_command_in_worktree` / `_serve_command_in_main` / `_finalize_static` / `_remove_serving_worktree` / `_register_serving_instance` / `_unregister_serving_instance` / `_evict_spec_serving` / `_current_instance_base_url` / `_ensure_app_reachable` / `_port_responds` / `_open_boot_log` / `_read_boot_log_tail` / `_rewrite_scenario_port` / `_serving_port_for_spec` / `_current_verify_round`
- [x] 4.8 搬 `judge_gate.py`：`_judge_dispatch_gate` / `_judge_hard_cap_freeze` / `_judge_rerun_count` / `_all_green_fast_path` / `_last_planner_cost_usd` / `_last_planner_run_cost` / `_write_degrade_context` / `_clear_degrade_context`
- [x] 4.9 搬 `escalation.py`：`_handle_env_blocked_inconclusive` / `_write_inconclusive_loop_signal` / `_env_whitewash_gate` / `_escalate_env_blocked` / `_update_warning_streaks` / `_warning_stale_triage_alert` / `_scenario_defect_reroute_gate` / `_escalate_scenario_defect_reroute` / `_handle_judge_env_declared` / `_judge_bugs_declare_env` / `_speculative_bug_found_gate`
- [x] 4.10 搬 `verdict_evidence.py`：`_verify_verdict_evidence` / `_verdict_violations_evidence` / `_write_verdict_violations` / `_clear_verdict_violations` / `_verdict_violations_path` / resynthesis 族 / `_record_verdict_adoption` / `_persist_verdict_cache` / `_verified_verdict_persisted` / `_verified_gate_refuses`
- [x] 4.11 搬 `legacy.py`：`_run_legacy_verification` 及其读取辅助
- [x] 4.12 门面 re-export 本组符号；全量 pytest + import 校验，独立 commit

## 5. 阶段 4：pipeline 骨架与包成型

- [x] 5.1 建 `pipeline.py`：`VerificationPipeline` 门面组装 + `_run_three_stage_verification` **整体搬移**（内部逻辑不动）
- [x] 5.2 删除 `_legacy.py` 残壳（旧 `verification.py` 已在 4.1 改名，届时不应再存在同名模块）；`__init__.py` 导出 `VerificationPipeline` 与 D8 名单中的全部既有公开符号
- [x] 5.3 逐条执行契约清单：`python -c` 验证全部公开符号可导入；确认 `self._pm._` 回引为 0
- [x] 5.4 `core/pm_engine/engine.py` 的委托路径校验；全量 pytest 全绿，独立 commit

## 6. 阶段 5：代码格式化统一

> 本任务是由可读性重构序列中的**最后一个 spec 承载的全局格式化收口**（用户 2026-09-15 要求）：在完成全部结构性拆分后，统一全仓代码的换行、缩进、空行等排版不一致。

- [x] 6.0 **前置条件确认**（design D7）：确认 `refactor-dashboard-data-module` / `refactor-agent-runner-module` 已合入或无在途未合并改动；否则本阶段推迟至两者合入后执行
- [x] 6.1 选定格式化工具并**落盘到磁盘指定位置**：优先使用 `ruff format`（若环境无网络/无法安装，回退 `black`，再回退 `autopep8`）；工具 MUST 固定到项目内可复现位置（如 `.fenix/tools/` 或其安装脚本 `scripts/`），并在仓库文档记录版本与调用方式
- [x] 6.2 以**最小扰动**配置格式化：`line-length` 取当前主流（100），仅对 `core/`、`bin/`、根 `fenixd.py` 的 `*.py` 生效；MUST NOT 改动 `agents/`、`docs/`、`spec/`、`*.md`
- [x] 6.3 运行格式化并**独立 commit**（格式化提交 MUST 与任何逻辑改动分离，便于 `git blame` 与回滚）
- [x] 6.4 提交后跑**全量回归测试**（`bin/run_full_suite.py`），确认格式化未引入任何失败；对比基线失败集合
- [x] 6.5 记录格式化前后的差异规模（改动文件数与行数）与工具版本于 `formatting-report.md`

## 7. 阶段 6：收尾验证

- [x] 7.1 运行 `tests/test_verification_modules_contract.py`（子模块职责、回引为 0、行数上限、大函数仅搬移）
- [x] 7.2 全量 `bin/run_full_suite.py`（**必须全量回归，不得只跑子集**）+ 疑点清单最终汇报（向用户汇报，代码不动）
- [x] 7.3 经用户确认时机后 `touch .fenix/restart_request` 重启 daemon 并冒烟验证（重构收尾前不得重启）

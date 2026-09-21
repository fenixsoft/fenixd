# Design: refactor-verification-module

## Context

`core/pm_engine/verification.py` 6304 行、`VerificationPipeline` 约 97 个方法，混合 10 类职责。它由 `refactor-core-packages` 从 `core/pm_engine.py` 提取而来，当时只做到「方法搬家」，依赖没有解耦——`self._pm.*` 回引达 495 处（其中私有回引 91 处 / 40 个不同目标），直接调用门面私有方法（`self._pm._enqueue`、`self._pm._read_verdict`、`self._pm._send_human_escalation_alert`）。本变更是在此基础上做第二层拆分 **并** 引入显式依赖注入。

约束：
- **零行为变化**，全量 pytest 不引入新失败；
- 外部与测试引用路径零修改；
- 这是本次重构序列中**风险最高**的一步（文件最大、回引最多），故排在 `data` / `runner` 两个先行拆分**之后**执行（依赖链保证）；
- 不得以绝对行号锚定。

## Goals / Non-Goals

**Goals**
- 按职责拆为子包，每模块可整文件理解。
- 引入 `PipelineContext`，消灭对门面**私有方法**的回引（公共依赖 logger/state_machine/config/project_root 收敛为 context 成员）。
- 沿用已建立的包化 + 门面范式。

**Non-Goals**
- 不在本变更拆分 `_run_three_stage_verification` 的函数体（1165 行）——只把它整体迁入 `pipeline.py` 骨架，内部拆分另立 spec。
- 不改验证语义、裁决规则、门禁阈值。

## Decisions

### D1：`PipelineContext` 显式注入（本变更的核心决策）
定义 `PipelineContext` 数据类，显式成员：`logger`、`project_root`、`state_machine`、`config_reader`（读 `_get_config` 的能力）、`escalation_notifier`（`_send_human_escalation_alert` 的能力）、`enqueue`（派发入队）。`VerificationPipeline` 构造时接收 context；各子组件经 context 访问，MUST NOT 再经 `self._pm._<private>` 回引。

**分期**：先替换**私有方法**回引（破坏封装、最危险），再替换高频只读依赖（logger/project_root/state_machine）。每期独立 commit。

替代方案（否决）：仅按文件搬移、保留 `self._pm` 回引——会把门面耦合原样复制到新子模块，拆分收益大打折扣。故本变更必须同时做注入。

### D2：分组边界即交付契约

| 新子模块 | 迁入内容（方法名聚类） |
|---|---|
| `pipeline.py` | 门面骨架 + `_run_three_stage_verification`（整体搬移，内部不拆）+ `__init__` 组装 |
| `serving.py` | `_ensure_serving_worktree` / `_serve_static_in_*` / `_serve_command_*` / `_finalize_static` / `_remove_serving_worktree` / `_register/_unregister_serving_instance` / `_evict_spec_serving` / `_current_instance_base_url` / `_ensure_app_reachable` / `_port_responds` / `_open_boot_log` / `_read_boot_log_tail` / `_rewrite_scenario_port` / `_serving_port_for_spec` / `_current_verify_round` |
| `scenario_gate.py` | `_apply_scenario_freeze` / `_apply_interaction_contract` / `_load_frozen_scenarios` / `_render_scenario_change_section_to_report` / `_write_verify_contract_missing` / `_run_scenario_static_check` / `_run_contract_static_check` |
| `verdict_evidence.py` | `_verify_verdict_evidence` / `_verdict_violations_evidence` / `_write/_clear_verdict_violations` / `_verdict_violations_path` / resynthesis 族（`_resynthesis_directive_path` / `_read/_clear_resynthesis_directive` / `_resynthesis_directive_scenarios` / `_write_resynthesis_directive` / `_escalate_dedup_resynthesis` / `_handle_attr_dedup_rejection` / `_handle_scenario_requeue` / `_clear_requeue_manifest`）/ `_record_verdict_adoption` / `_persist_verdict_cache` / `_verified_verdict_persisted` / `_verified_gate_refuses` |
| `judge_gate.py` | `_judge_dispatch_gate` / `_judge_hard_cap_freeze` / `_judge_rerun_count` / `_all_green_fast_path` / `_last_planner_cost_usd` / `_last_planner_run_cost` / `_write/_clear_degrade_context` / `_last_planner_cost_usd` |
| `escalation.py` | `_handle_env_blocked_inconclusive` / `_write_inconclusive_loop_signal` / `_env_whitewash_gate` / `_escalate_env_blocked` / `_update_warning_streaks` / `_warning_stale_triage_alert` / `_scenario_defect_reroute_gate` / `_escalate_scenario_defect_reroute` / `_handle_judge_env_declared` / `_judge_bugs_declare_env` / `_speculative_bug_found_gate` |
| `infra_classify.py` | `_verifier_error_is_infra` / `enrich_failure_class` / `_record_infra_failure` / `_detect_uniform_verify_failure` / `reclassify_infra_rounds` / `_fail_history_path` / `_read/_append/_clear_fail_history` / `_scenario_classification_distribution` / `_failed_scenario_ids` / `_normalize_fail_signature` |
| `legacy.py` | `_run_legacy_verification` 及其读取辅助（`_read_verifier_result` / `_read_planner_result` / `_read_verdict` 若仅 legacy 用则随迁） |
| `branch_guard.py` | `_implementation_branch_has_commits` / `_branch_commit_count` / `_implementer_zero_change` / `_deliverable_gate_missing` / `_tasks_md_relint_from_branch` / `_tasks_md_relint_from_worktree` / `_disputed_deliverables` / `_extract_replan_error_items` / `_replan_errors_unconsumed` / `resolve_env_blocked_reset_path` / `_branch_merged_into_tree` |
| `report_gate.py` | `_read_verify_report` / `_ensure_verification_report` / `_check_verification_gate` / `_verifier_result_is_stale` / `VerdictReadResult` |

> 分组以职责自洽为准；跨组函数按主要职责归一组并在门面 re-export。
>
> **分组表即交付契约，MUST 覆盖 `VerificationPipeline` 的全部方法，不留未归属项**。目前表内以
> 「resynthesis 族」概括的 8 个方法与 `_read_verifier_result` / `_read_planner_result` / `_read_verdict`
> 三项读取辅助，以及 `VerdictReadResult` 的 `ok` / `success` / `failure` / `__repr__`，MUST 在
> 阶段 0 的 `contract-inventory.md` 中逐名落位（无归属者 MUST 显式归入某一组或标注「保留在
> `pipeline.py` 门面」，禁止留白）。

### D3：搬移顺序——先注入后搬移
先在**原文件内**引入 `PipelineContext` 并完成私有回引替换（此时文件结构未动，回归可控），**再**按 D2 分组搬移。理由：注入是行为敏感改动，放在单文件内做更易定位回归；搬移是纯结构改动，随后做风险低。

### D4：`_run_three_stage_verification` 整体搬移不拆分
1165 行函数内部已有阶段段落注释；本变更把它整体迁入 `pipeline.py`，**内部逻辑不动**。若拆内部，控制流改动面巨大，另立 spec。

### D5：门面与既有 `engine.py` 委托
`core/pm_engine/engine.py` 现有对 `VerificationPipeline` 的委托保持不变；新的子包 `__init__.py` 导出 `VerificationPipeline` 与 `reclassify_infra_rounds` 等既有公开符号。

### D6：不使用绝对行号锚定。

### D7：末段代码格式化统一（本 spec 为可读性序列最后一个）
全部结构性拆分完成后，用一个**独立的格式化 commit** 统一 `core/`、`bin/`、根 `fenixd.py` 下 `*.py` 的换行/缩进/空行（作用域以 tasks 6.2 为准；MUST NOT 触及 `agents/`、`docs/`、`spec/` 与任何 `*.md`——「全仓」仅指上述代码目录，不代表可改动文档）。工具选定为 `ruff format`（无网络时回退 `black`/`autopep8`），落盘到项目内固定位置以便复现；格式化与逻辑改动分离提交，提交后 MUST 跑全量回归。**理由**：格式化会触及几乎每个文件，若与拆分混在同一提交，会淹没结构性 diff 且难以回滚；作为序列收口，此时代码已稳定、冲突面最小。

> **前置条件（MUST）**：格式化提交前 MUST 确认 `refactor-dashboard-data-module` / `refactor-agent-runner-module` 两个同序列变更已合入或已让出工作区；若其分支仍有未合并改动，格式化提交 MUST 推迟至两者合入后执行，避免全仓级 diff 与在途分支大面积冲突。「零行为变化」的验收口径对格式化提交同样适用（全量回归对比基线）。

### D8：同名包遮蔽的过渡方案——先改名入包，再逐组摘出
`core/pm_engine/verification.py` 改为 `core/pm_engine/verification/` 时，**同名包会遮蔽同名模块**（Python 对同目录下同名目录优先于同名 `.py`）。若按 tasks 4.1「建空包 `__init__.py`」直接落地，`from core.pm_engine.verification import VerificationPipeline` 会在同一瞬间全部失效（`core/pm_engine/engine.py:31` 与 24 个测试文件），与「逐组搬移、每组建绿、独立 commit」的验收自相矛盾。

故 MUST 采用与 `refactor-dashboard-data-module` D7 一致的过渡路径：
1. `verification.py` → `verification/_legacy.py`（先改名入包，**不拆分**）；
2. `__init__.py` 立即以显式名单 re-export `_legacy` 的全部既有公开与私有名字（含 `VerificationPipeline`、`VerdictReadResult`、`reclassify_infra_rounds`、`resolve_env_blocked_reset_path`、`_branch_merged_into_tree`、`_SCENARIO_REPAIR_MAX_ROUNDS`、`_MAX_JUDGE_RERUNS` 等），此 commit 必须全量回归全绿；
3. 随后逐组把方法从 `_legacy.py` 摘到目标子模块，并同步更新 `__init__` 的 re-export；
4. `_legacy.py` 仅剩空壳时删除。

禁止在旧 `verification.py` 仍存在时先建同名包目录。

### D9：模块级名字与 patch 语义保持（回归硬门）
既有测试以**字符串路径 patch 模块级名字**，这些名字会随所属子模块迁移，拆分后 patch 将失效（`AttributeError`，或更危险地静默空转使测试失去意义）。已清点：

| patch 目标 | 调用点 |
|---|---|
| `core.pm_engine.verification.subprocess.run` | `tests/test_blocked_reverify_gate.py`（11 处）、`tests/test_frozen_scenario_schema_migration.py`（3 处） |
| `core.pm_engine.verification.ensure_main_tree_deps` / `run_prepare_steps` / `load_verify_contract` | `tests/test_main_tree_deps_provision.py:172,173,189,203,204,218` |
| `core.pm_engine.verification.rewrite_scenarios_origin` | `tests/test_verify_command_port.py:287` |

（`rewrite_scenarios_origin` / `ensure_main_tree_deps` / `run_prepare_steps` / `load_verify_contract` 现为 `verification.py` 顶层 import；`subprocess` 为顶层 import 且在文件内被调用 11 次。）

处理规则：
- 包 `__init__` MUST 保留上述名字的引用；**子模块中的调用点 MUST 经包命名空间或保留的共享模块延迟解析**（对齐 dashboard 先例 D8 的「调用点经门面延迟解析」），使 `patch("core.pm_engine.verification.<name>")` 继续命中。
- 阶段 0 MUST 固定这 15+ 处 patch 的当前语义基线；阶段 3 每组搬移后 MUST 复跑上述 4 个测试文件。
- 若某处确无法保持 patch 语义，MUST 在阶段 0 记录并作为「测试引用零修改」的**显式例外**上报用户裁决，MUST NOT 静默改测试或删断言。

### D10：组件间调用与依赖方向（`PipelineContext` 的覆盖边界）
`PipelineContext` 只承载**跨出验证域**的外部依赖（D1 六成员），MUST NOT 承载验证域内部方法。阶段 0 契约清单已确认 `self._pm._` 私有回引含约 30 个目标是 `VerificationPipeline` **自身方法经 `PMEngine` 门面绕行**（如 `self._pm._apply_scenario_freeze`(3)、`self._pm._ensure_verification_report`(4)、`self._pm._read_verdict`(4)、`self._pm._clear_verdict_violations`(3)、`self._pm._env_whitewash_gate`(3)、`self._pm._verifier_error_is_infra`(2) 等）。替换规则：
- 这一类 MUST 改为**经组合组件直接调用**（如 `self._scenario_gate.apply_scenario_freeze(...)`），MUST NOT 再经 `self._pm` 绕行；
- 仍属 `PMEngine` 私有且 D1 未给成员的目标（`_is_fix_spec`(2)、`_on_spec_verified`(2)、`_on_spec_bug_found`(2)、`_read_implementer_result`(1)、`_exempt_infra_run_budget`(1)、`_ENV_INFRA_MARKERS`(1)）MUST 由 D1 补齐 context 成员（名字自定），否则「`grep -c 'self\._pm\._' == 0`」在数学上不可达；
- 类别成员的最终名单 MUST 覆盖阶段 0 契约清单中**全部 40 个**私有回引目标（其中 9 个为 `PMEngine` 私有：`_send_human_escalation_alert` / `_get_config` / `_enqueue` / `_is_fix_spec` / `_on_spec_verified` / `_on_spec_bug_found` / `_read_implementer_result` / `_exempt_infra_run_budget` / `_ENV_INFRA_MARKERS`），验收时逐名核对，而非仅核对 `grep` 计数。
- 子模块间依赖 MUST 单向、互不 `import`：跨组调用经 `pipeline.py` 组合根注入的组件引用完成，禁止 `verdict_evidence` ↔ `scenario_gate` 之类的相互 import（会引入循环 import）。

## Risks / Trade-offs

- [482 处回引替换引入行为漂移] → D3 先在单文件内做、characterization tests 护航、每期独立 commit；重点回归 `test_pm_verification`（67 用例）、`test_verdict_*`、`test_env_sanity_gate`。
- [context 成员语义与门面行为不一致] → `config_reader` / `escalation_notifier` 以**委托到原门面方法**的方式实现，保证语义逐字节一致（只是不再直接 `self._pm._x`）。
- [循环 import：子包与 engine 门面] → 子模块不 import engine；context 由 engine 在构造时注入。
- [本变更体量最大、周期最长] → 已是依赖链最后一环；拆为两个 spec 会拉长总时长，故合并为单 spec 但严格分阶段提交。

## Migration Plan

1. 阶段 0：characterization tests（重点 `_run_three_stage_verification` 的可观测输入输出、裁决采纳、env 升级路径）+ 疑点清单 + 基线。
2. 阶段 1：文件内引入 `PipelineContext`，替换私有回引（`_send_human_escalation_alert` / `_get_config` / `_enqueue` / `_read_verdict`），独立 commit。
3. 阶段 2：替换高频只读依赖回引（logger/project_root/state_machine），独立 commit。
4. 阶段 3：按 D2 分组搬移到 `core/pm_engine/verification/` 子包，逐组 commit。
5. 阶段 4：删除旧 `verification.py`，门面成型，逐一验证 import。
6. 阶段 5：全量 pytest + 疑点清单汇报；daemon 重启经用户确认。

**回滚**：每期/每组独立 commit。

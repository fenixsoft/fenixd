# Contract Inventory: refactor-long-functions

## 概述

本文档是 `_run_three_stage_verification`（pipeline 侧）与 `_execute_agent_inner`（runner 侧）的静态清点结果，逐块落位到 design D1 分块表。**纯静态记录，不含任何修改**——仅记录拆分前的结构基线，供后续提取阶段（阶段 1–4）对账。

清点方法：Python `ast` 模块解析源码，按 D1 分块表符号锚点提取每块的局部变量写点 / 读点，并做跨块读写（粘合变量）分析。行号为当前工作树实测值（design D8：仅现状描述，不进入任务锚定）。

---

## 1. `_run_three_stage_verification`（pipeline.py，L563–L1819，实测 1257 行）

### 1.1 分块表（10 块，D1 全覆盖，不留未归属块）

| 块 | 符号锚点 | 范围（行号） | 可无副作用提取 | 提取目标方法 | 说明 |
|---|---|---|---|---|---|
| B0 | 入口守卫 + importlib.reload | L563–633 | **是** | `_check_entry_status` / `_reload_verify_engine_modules` | 含 `import asyncio/importlib/sys`（D4）；**已提取** |
| B1 | 循环变量初始化 + 冻结损坏升级 | L638–677 | 是 | `_load_frozen_or_escalate` | `_load_frozen_scenarios` + corrupt 分支 escalate；**已提取**（循环变量声明留主函数，见 §1.3 注） |
| B2 | `while True` 循环：出题侧 | 循环体前半 | **否**（3 continue + 1 break + 10 return，留循环体内） | `_plan_scenarios_loop` | **D2 保留：循环体，本变更不提取** |
| B3 | `while True` 循环：阶段2 执行 | 循环体后半 | 部分（引擎执行段可提，env_error 回写段留循环体） | `_execute_stage2` | D2 部分提取；**引擎执行段已提取**，env_error 回写段留循环体 |
| B4 | 阶段2 门禁 | L1151–1210 | 是 | `_run_stage2_gates` | 不可达门 / 失联门 / 同因哨 / 全绿快道；**已提取**（返回 fail_count/judge_result/aborted 三值） |
| B5 | judge 派发与失败 | L1215–1302 | 是 | `_dispatch_judge_or_reuse` | `_judge_dispatch_gate` / 三让位 / D6 二次状态核对；**已提取** |
| B6 | 裁决证据分类校验 | L1304–1470 | **是**（可每 cause 一方法） | `_handle_verdict_evidence_rejection` | 7 个 cause 分支；**已提取** |
| B7 | verdict 读取 fail-closed | L1475–1569 | 是 | `_read_verdict_failclosed` | warning streak / `_read_verdict` / 状态核对 / 不可读重派→blocked；**已提取** |
| B8 | scenario-repaired 重入 | L1570–1623 | 是（尾递归保持原样） | `_handle_scenario_repaired` | 修复预算 / 冻结记账 / 空集拒绝 / 递归调用；**已提取** |
| B9 | bug-found 应用 | L1624–1819 | 是（纯编排） | `_apply_bug_found` | 5 道门禁 → transition → spawn 抑制 → infra 归因；**已提取** |
| B10 | verified 应用 | L1624–1819 内联 | 是（纯编排） | `_apply_verified` | 进度核对 / 报告闸 / 洗白门 → transition（7 计数器归零）；**已提取** |

> 注：B9 与 B10 是终态分支（`verifier_status == 'bug-found'` / `'verified'`），在同一 If 复合体内，行号区间重叠；B10 的提取目标独立登记。

### 1.2 逐块局部变量清单

#### B0: 入口守卫 + importlib.reload（L563–633）

- 写点：`_entry_status`, `_verify_modules`, `mod_name`
- 读点：`spec_name`, `self`, `importlib`, `sys`, `_entry_status`, `_verify_modules`
- 函数内 import：`asyncio`, `importlib`, `sys`（D4：MUST 保留在运行时函数体内）
- 跨块读取：`spec_name`（参数）；`self._context`

#### B1: 循环变量初始化 + 冻结损坏升级（L638–677）

- 写点：`verify_dir`, `replan_left`, `replan_feedback`, `prev_replan_error`, `report`, `app_reachable`, `reach_note`, `frozen`, `detail`
- 读点：`spec_name`, `self`, `frozen`, `detail`
- 粘合变量（跨块）：`verify_dir`→B2、`replan_left`→B2、`replan_feedback`→B2、`prev_replan_error`→B2、`report`→B2/B4/B5/B9、`app_reachable`→B2/B4、`reach_note`→B2/B4、`frozen`→B2、`detail`→B6

#### B2: `while True` 循环（出题侧，L678–1149 循环体前半）

- 写点：`frozen`(复用分支), `cov`, `fb`, `fb_text`, `_stage1_status`, `plan_result`, `p_err`, `cancelled_err`, `plan_read`, `plan_status_text`, `_sv_cache`, `_sv_entry`, `contract`, `scenarios_path`, `scenario_root`, `scenarios`, `scenarios`(重写), `engine`, `env_error`, `cur_items`, `prev_items`, `_parallel_override`, `_wt_path`, `freeze_result`, `reject_detail`, `user_blocked`, `app_reachable`(重写), `reach_note`(重写), `report`(重写), `replan_feedback`(重写), `replan_left`(重写), `prev_replan_error`(重写), `selfcheck_err`
- 读点：`frozen`, `cov`, `spec_name`, `verify_dir`, `replan_feedback`, `plan_result`, `cancelled_err`, `plan_read`, `plan_status_text`, `_sv_cache`, `_sv_entry`, `contract`, `scenarios_path`, `scenario_root`, `scenarios`, `engine`, `env_error`, `cur_items`, `prev_items`, `app_reachable`, `reach_note`, `report`, `replan_left`, `prev_replan_error`, `selfcheck_err`, `_apply_interaction_contract`, `_run_scenario_static_check`, `_run_contract_static_check`, `load_scenarios`, `asyncio`, `VerifyEngine`, `selfcheck_contract_light`
- 函数内 import：`VerifyEngine`, `load_scenarios`（L635–636，D4：MUST 保留在运行时函数体内）
- 控制流：`continue` × 3、`break` × 1（L1149）、`return` × 10（D2：不提取）

#### B3: `while True` 循环（阶段2 执行，L678–1149 循环体后半）

- 写点：`scenarios`, `engine`, `env_error`, `app_reachable`, `reach_note`, `report`, `user_blocked`
- 读点：`scenarios`, `engine`, `spec_name`, `verify_dir`, `contract`, `scenarios_path`, `scenario_root`, `app_reachable`, `reach_note`
- 控制流：env_error 回写段含 `continue`（D2：该段留循环体内，只提引擎执行段）

#### B4: 阶段2 门禁（L1151–1210）

- 写点：`fail_count`
- 读点：`report`, `app_reachable`, `reach_note`, `spec_name`, `fail_count`, `self`
- 粘合变量：`fail_count`→B5；`report`（来自 B2）；`app_reachable`/`reach_note`（来自 B2）

#### B5: judge 派发与失败（L1215–1302）

- 写点：`judge_result`, `gate`, `j_err`, `cancelled_err`, `_apply_status`
- 读点：`report`, `fail_count`, `gate`, `j_err`, `cancelled_err`, `judge_result`, `spec_name`, `_apply_status`, `self`
- 粘合变量：`judge_result`→B6/B9；`_apply_status`→B6/B7；`cancelled_err`（自 B2 读）

#### B6: 裁决证据分类校验（L1304–1470）

- 写点：`verdict_ret`, `cause`, `violations`, `dispatch_error`, `detail`, `v`, `verdict_ret`(重写)
- 读点：`verdict_ret`, `cause`, `violations`, `dispatch_error`, `detail`, `v`, `spec_name`, `judge_result`, `self`
- 7 个 cause 分支：`batch_attribution_dedup`, `dispatch_frozen`, `dispatch_cancelled`, `violations`, `dispatch_error`(其余)
- 粘合变量：`verdict_ret`→B7（作为读取依据）；`judge_result`（来自 B5）

#### B7: verdict 读取 fail-closed（L1475–1569）

- 写点：`verdict_result_path`, `verifier_result`, `verifier_status`, `_apply_status`, `retry_status`, `retry_judge`, `triage_hits`, `reject_detail`, `freeze_result`
- 读点：`verdict_result_path`, `verifier_result`, `verifier_status`, `_apply_status`, `retry_status`, `retry_judge`, `spec_name`, `_repair_depth`, `triage_hits`, `reject_detail`, `freeze_result`, `self`
- 粘合变量：`verifier_status`→B8/B9；`_apply_status`（自 B5/B6 读）；`reject_detail`→B8

#### B8: scenario-repaired 重入（L1570–1623）

- 写点：`freeze_result`, `reject_detail`
- 读点：`verifier_status`, `spec_name`, `_repair_depth`, `freeze_result`, `reject_detail`, `self`
- 控制流：尾递归 `self._run_three_stage_verification(spec_name, _repair_depth=_repair_depth+1)`（保持原样）

#### B9: bug-found 应用（L1624–1819）

- 写点：`failure_class`, `vblocker`, `cur`, `report_blocker`
- 读点：`verifier_status`, `spec_name`, `judge_result`, `report`, `failure_class`, `vblocker`, `cur`, `report_blocker`, `self`
- 粘合变量：`judge_result`（来自 B5）、`report`（来自 B2/B5）
- 5 道门禁（既有方法）：`_verifier_result_is_stale` / `_check_verification_gate` / `_deliverable_gate_missing` / `_branch_commit_count` / `_implementer_zero_change`

#### B10: verified 应用（L1624–1819 内联）

- 写点：`_apply_status`(内联核对)
- 读点：`verifier_status`, `spec_name`, `report`, `self`
- 7 个计数器归零（transition 参数）、采纳落盘、`on_spec_verified`

### 1.3 主函数收敛口径

- 拆分前长度：1257 行（L563–L1819）
- 目标：≤ 830 行（下降 ≥ 1/3；D2 保留的 472 行循环体计入）
- 新提取方法上限：≤ 300 行（spec 建议 ≤ 200 行，design 阈值 300）

**拆分后实测**（阶段 1/2 完成）：

- `_run_three_stage_verification`：**~520 行**（较 1257 行下降 > 1/2，< 830 达标；D2 保留的 while True 循环体计入）。
- **最终实测**（阶段 2 收口后复测）：**435 行**（较 1257 行下降 > 2/3，< 830 达标；D2 保留的 while True 循环体计入）。
- 提取方法长度均 ≤ 300 行：

| 提取方法 | 行数 |
|---|---|
| `_check_entry_status` | 16 |
| `_reload_verify_engine_modules` | 59 |
| `_handle_verdict_evidence_rejection` | 167 |
| `_read_verdict_failclosed` | 99 |
| `_apply_bug_found` | 127 |
| `_apply_verified` | 80 |
| `_load_frozen_or_escalate` | 35 |
| `_run_stage2_gates` | 73 |
| `_dispatch_judge_or_reuse` | 97 |
| `_handle_scenario_repaired` | 64 |
| `_execute_stage2` | 136 |

> B1 注：循环变量声明（verify_dir/replan_left/…）保留在主函数——它们在 B2 循环体内被重写，属循环状态，提取为方法会导致跨方法回写循环变量，违反「等价搬移」且无收益；B1 的可提取段（冻结加载 + 损坏升级）已提取为 `_load_frozen_or_escalate`。

---

## 2. `_execute_agent_inner`（runner.py，L1561–L2586，实测 1026 行）

### 2.1 分块表（10 块，D1 全覆盖，不留未归属块）

| 块 | 符号锚点 | 范围（行号） | 可无副作用提取 | 提取目标方法 | 说明 |
|---|---|---|---|---|---|
| R0 | 默认参数初始化 + 跨 attempt 状态变量 | L1561–1604 | — | （并入 D3 `_AttemptState`） | 14 个跨 attempt 标量 |
| R1 | attempt 顶守卫 | L1605–1673 | 部分（3 写回变量） | `_attempt_top_guards` | frozen 终止 / 取消旗标（worktree 三型处置）/ 日限检查 |
| R2 | 候选链选择 | L1686–1756 | **是**（`chain_cursor` 回传） | `_resolve_provider_candidate` | 模型分配 → 指针推进 → 耗尽/4xx 熔断 → 记当日 attempt |
| R3 | worktree 复用/新建 | L1758–1894 | 部分 | `_prepare_worktree` | 路径校验 / create 失败重试让位 / `used_wts` / dev-server / provider_marker / 路由地图 |
| R4 | 子循环 try 体 | L1916–2037 | **部分**（仅 `_copyback_run_result` 戳拷回子段 L2000–2023） | `_copyback_run_result` | 其余留循环体内 |
| R5 | except 取消/产物门 | L2038–2163 | 部分 | `_handle_artifact_gate_retry` | RunCancelledError 收口 / ArtifactGateError 记账 + 退避；**已提取**（跨边界 return/continue/break 经五元组回传） |
| R6 | except 兜底 | L2164–2313 | **最难**（先内提两小步） | `_classify_and_maybe_retry` | shutdown 守卫 / 秒挂 / 4xx 熔断 / 瞬断分类与原地重试；**已内提两小步**：`_record_4xx_or_transient` + `_maybe_in_place_retry`；剩余主体（shutdown 守卫/秒挂/session 提取/resume 清理/switch 冷却）**D2 保留：循环体，本变更不提取** |
| R7 | 成功终态 | L2314–2420 | 部分 | `_finalize_success` | 半开探针闭合 / wt_dirty 取证 / 终态零提交门 / worktree 分型 / token 入账 |
| R8 | 失败终态 | L2421–2520 | 部分 | `_finalize_failure_keep` | 重试等待 vs 终态 keep 分型 |
| R9 | 循环后收口 | L2526–2586 | **是** | `_exhausted_result` | 全重试耗尽三型返回 + token 入账 |

### 2.2 逐块局部变量清单

#### R0: 默认参数初始化 + 状态变量（L1561–1604）

- 写点：`used_wts`, `handed_off`, `max_retries`, `start_time`, `wt_path`, `session_id`, `session_provider`, `chain_cursor`, `last_provider_used`, `kept_wt_path`, `provider_name`, `model`, `usage_info`, `turns`, `cancelled_flag`, `cancel_reason`, `shutdown_interrupted`
- 读点：`used_wts`, `handed_off`, `pre_wt_path`, `time`, `self`
- 参数：`spec_name`, `agent_type`, `run_id`, `pre_wt_path`, `conflict_summary`, `used_wts`, `handed_off`
- 14 个跨 attempt 标量（D3 `_AttemptState` 候选）：`wt_path`, `provider_name`, `model`, `chain_cursor`, `session_id`, `session_provider`, `transient_retries`, `resume_failures`, `kept_wt_path`, `cancelled_flag`, `cancel_reason`, `shutdown_interrupted`, `usage_info`, `turns`（另 `last_provider_used`, `start_time`）

#### R1: attempt 顶守卫（L1605–1673）

- 写点：`attempt`, `attempt_run_id`, `meta`, `cancel_reason`(重写), `kept_wt_path`(重写)
- 读点：`spec_name`, `agent_type`, `max_retries`, `run_id`, `start_time`, `turns`, `usage_info`, `provider_name`, `model`, `wt_path`, `handed_off`, `cancel_reason`, `meta`, `time`, `self`
- 写回变量：`cancelled_flag`, `cancel_reason`, `kept_wt_path`, `wt_path`(清理路径), `handed_off`(三型处置)

#### R2: 候选链选择（L1686–1756）

- 写点：`chain`, `chain_cursor`, `provider`, `model`, `provider_name`, `first_4xx_open`, `circuit_err`, `exhausted_err`
- 读点：`agent_type`, `spec_name`, `run_id`, `start_time`, `turns`, `usage_info`, `attempt_run_id`, `chain`, `chain_cursor`, `model`, `self`
- 粘合变量：`chain_cursor` 回传（D1）；`provider`/`model`/`provider_name`→R3/R4/R5/R6/R7/R8

#### R3: worktree 复用/新建（L1758–1894）

- 写点：`wt_path`(重写), `reuse_worktree`, `last_provider_used`, `error_msg`, `switch_msg`, `last_model`
- 读点：`spec_name`, `agent_type`, `attempt`, `attempt_run_id`, `max_retries`, `provider_name`, `model`, `used_wts`, `wt_path`, `self`
- 粘合变量：`wt_path`（写回，跨 R1/R4/R5/R6/R7/R8 读）；`used_wts` 登记

#### R4: 子循环 try 体（L1916–2037）

- 写点：`prompt`, `env_overrides`, `model_override`, `output`, `turns`(重写), `run_session_id`, `session_id`(重写), `session_provider`(重写), `usage_info`(重写), `wt_result`, `root_result`, `raw`, `role`, `payload`, `k`, `v`, `gate_err`, `success`, `error`, `transient_retries`, `transient_budget`, `resume_failures`, `sub_run_id`
- 读点：`spec_name`, `agent_type`, `conflict_summary`, `wt_path`, `provider`, `model`, `session_id`, `session_provider`, `provider_name`, `reuse_worktree`, `attempt_run_id`, `transient_retries`, `chain`, `chain_cursor`, `sub_run_id`, `run_session_id`, `self`
- **`_copyback_run_result` 候选子段（L2000–2023）**：`wt_result`/`root_result`/`raw`/`role`/`payload` 只在此段使用，零写点零跨边界控制流——可无副作用提取
- 函数级 import：`json`, `Dict`, `AGENT_TYPE_TO_ROLE`, `DEFAULT_GATEWAY_MODEL`（模块级，非函数内）

#### R5: except 取消/产物门（L2038–2163）

- 写点：`output`, `turns`, `success`, `cancelled_flag`, `cancel_reason`, `error`, `usage_info`, `gate_err`, `backoff`, `transient_retries`
- 读点：`e`, `agent_type`, `spec_name`, `attempt`, `attempt_run_id`, `error`, `sub_run_id`, `transient_budget`, `transient_retries`, `provider_name`, `wt_path`, `reuse_worktree`, `start_time`, `turns`, `usage_info`, `model`, `run_id`, `datetime`, `timezone`, `json`, `self`
- 跨块控制流：`break`（L2055 取消退出 / L2163 预算耗尽）/ `continue`（L2162 让位重派）——D2 留循环体内

#### R6: except 兜底（L2164–2313）

- 写点：`output`, `turns`, `success`, `error`, `shutdown_interrupted`, `usage_info`, `code`, `was_half_open`, `st`, `exc_stderr`, `exc_exit`, `exc_has_result`, `resume_dead`, `is_transient`, `l`, `backoff`, `transient_retries`
- 读点：`e`, `spec_name`, `agent_type`, `sub_run_id`, `attempt`, `attempt_run_id`, `provider_name`, `model`, `error`, `start_time`, `turns`, `usage_info`, `run_id`, `time`, `datetime`, `timezone`, `self`
- 写点最多的块（17 个），先内提两小步（瞬断重试判定 / 秒挂记账），主体留循环体内（D2）

#### R7: 成功终态（L2314–2420）

- 写点：`branch`, `run_file`, `wt_dirty`, `sid`, `st`, `l`, `resume_failures`(重写), `chain_cursor`(重写), `session_id`(重写), `session_provider`(重写)
- 读点：`agent_type`, `spec_name`, `attempt_run_id`, `sub_run_id`, `run_id`, `success`, `error`, `wt_path`, `provider_name`, `model`, `turns`, `usage_info`, `start_time`, `chain`, `chain_cursor`, `resume_failures`, `time`, `self`
- 半开探针闭合：`_record_provider_probe(provider_name, success=True)`

#### R8: 失败终态（L2421–2520）

- 写点：`duration`, `kept_wt_path`(重写)
- 读点：`agent_type`, `spec_name`, `attempt`, `attempt_run_id`, `sub_run_id`, `run_id`, `success`, `error`, `output`, `wt_path`, `wt_dirty`, `branch`, `provider_name`, `model`, `turns`, `usage_info`, `start_time`, `cancelled_flag`, `shutdown_interrupted`, `max_retries`, `handed_off`, `time`, `self`
- 分型：重试等待（`_retry_backoff`）vs 终态 keep（`_finalize_keep`）

#### R9: 循环后收口（L2526–2586）

- 写点：`duration`
- 读点：`run_id`, `spec_name`, `agent_type`, `start_time`, `turns`, `usage_info`, `provider_name`, `model`, `cancelled_flag`, `shutdown_interrupted`, `error`, `kept_wt_path`, `max_retries`, `time`, `self`
- 三型返回：`cancelled_flag` / `shutdown_interrupted` / 全重试耗尽

### 2.3 主函数收敛口径

- 拆分前长度：1026 行（L1561–L2586）
- 目标：≤ 600 行（下降 ≥ 1/3；D2 保留的 419 行内层循环及其 except 收口计入）
- 新提取方法上限：≤ 300 行（spec 建议 ≤ 200 行，design 阈值 300）

**拆分后实测**（阶段 3/4 完成）：

- `_execute_agent_inner`：**430 行**（较 1026 行下降 > 1/2，< 600 达标；D2 保留的内层 while True + except 收口计入）
- 提取方法长度均 ≤ 300 行：

| 提取方法 | 行数 |
|---|---|
| `_attempt_top_guards` | 79 |
| `_resolve_provider_candidate` | 98 |
| `_prepare_worktree` | 127 |
| `_copyback_run_result` | 34 |
| `_record_4xx_or_transient` | 62 |
| `_maybe_in_place_retry` | 87 |
| `_handle_artifact_gate_retry` | 115 |
| `_finalize_success` | 96 |
| `_finalize_failure_keep` | 76 |
| `_exhausted_result` | 67 |

> **D2 保留说明**：R6 剩余主体（shutdown 守卫 / 秒挂记账 / session 提取 / resume 清理 / switch 冷却）含跨边界 `break`/`return`，按 D2 保持原位不拆，Task 5.5 确认。R6 已内提两小步（`_record_4xx_or_transient` + `_maybe_in_place_retry`），覆盖记账 + 原地退避决策核心路径。

---

## 3. 粘合变量总表（跨块读写，提取时 MUST 显式传递）

### 3.1 pipeline 侧

| 变量 | 写块 | 读块 | 传递方式 |
|---|---|---|---|
| `spec_name` | 参数 | 全部 | 参数透传 |
| `report` | B1/B2 | B2/B4/B5/B9 | 返回值（B2 循环体末）→ 后续块参数 |
| `frozen` | B1 | B1/B2 | 参数 |
| `verify_dir` | B1 | B2 | 参数 |
| `replan_left`/`replan_feedback`/`prev_replan_error` | B1/B2 | B2 | 循环变量（B1 初值，B2 内更新） |
| `app_reachable`/`reach_note` | B1/B2 | B2/B4 | 循环变量 |
| `fail_count` | B4 | B5 | 返回值 |
| `judge_result` | B5 | B6/B9 | 返回值 |
| `_apply_status` | B5/B7 | B6/B7 | 状态核对临时量 |
| `verdict_ret` | B6 | B7 | 返回值 |
| `verifier_status` | B7 | B8/B9 | 返回值 |
| `_repair_depth` | 参数 | B8 | 参数透传（尾递归） |
| `detail`/`reject_detail`/`freeze_result` | B1/B2/B6/B7/B8 | 各块 | 局部传递 |

### 3.2 runner 侧

| 变量 | 写块 | 读块 | 传递方式 |
|---|---|---|---|
| `spec_name`/`agent_type`/`run_id` | 参数 | 全部 | 参数透传 |
| `wt_path` | R0/R3 | R1/R4/R5/R6/R7/R8 | **`_AttemptState` 字段**（读 53 次） |
| `provider_name` | R0/R2 | R1-R9 | `_AttemptState` 字段（读 39 次） |
| `model` | R0/R2 | R1-R9 | `_AttemptState` 字段（读 20 次） |
| `chain_cursor` | R0/R2/R7 | R2/R4/R7 | `_AttemptState` 字段 |
| `session_id`/`session_provider` | R0/R4/R7 | R4 | `_AttemptState` 字段 |
| `transient_retries` | R4/R5/R6 | R4/R5/R6 | `_AttemptState` 字段 |
| `resume_failures` | R4/R7 | R7 | `_AttemptState` 字段 |
| `kept_wt_path` | R0/R1/R8 | R1/R9 | `_AttemptState` 字段 |
| `cancelled_flag` | R0/R5 | R8/R9 | `_AttemptState` 字段 |
| `cancel_reason` | R0/R1/R5 | R1 | `_AttemptState` 字段 |
| `shutdown_interrupted` | R0/R6 | R8/R9 | `_AttemptState` 字段 |
| `usage_info` | R0/R4/R5/R6 | R1/R2/R3/R6/R7/R8/R9 | `_AttemptState` 字段 |
| `turns` | R0/R4/R5/R6 | R1-R9 | `_AttemptState` 字段 |
| `start_time` | R0 | R1-R9 | `_AttemptState` 字段 |
| `last_provider_used` | R0/R3 | R3 | `_AttemptState` 字段 |
| `handed_off`/`used_wts` | 参数/可变集 | R1/R3/R4/R8 | 参数透传（set 可变） |
| `attempt`/`attempt_run_id` | R1 | R2-R8 | `_AttemptState` 字段 |
| `chain`/`provider` | R2 | R4/R7 | `_AttemptState` 字段 |
| `error`/`output`/`success`/`backoff` | R4/R5/R6 | R7/R8/R9 | `_AttemptState` 字段 |
| `wt_dirty`/`branch` | R7 | R8 | `_AttemptState` 字段 |

---

## 4. 既有测试依赖内部符号清单（拆分后 MUST 不破）

| 测试文件 | 依赖方式 | 依赖符号 |
|---|---|---|
| `test_turn_limit_lifecycle.py` | `setattr(rmod, "subprocess", ns)` | `core.agent_runner.runner.subprocess`（模块级名） |
| `test_impl_wip_checkpoint.py` | `setattr(runner_mod, "commit_wip_checkpoint", _boom)` | `core.agent_runner.runner.commit_wip_checkpoint` |
| `test_main_tree_deps_provision.py` | patch 模块级名 | `core.agent_runner.runner.*` |
| `test_verify_command_port.py` | patch 模块级名 | `core.pm_engine.verification.subprocess` |
| `test_blocked_reverify_gate.py` | patch 模块级名 | 同上 |
| `test_frozen_scenario_schema_migration.py` | patch 模块级名 | 同上 |
| 依赖 `patch("core.verify_engine.VerifyEngine")` 的文件 | 函数内 import（D4） | `VerifyEngine`（`_run_three_stage_verification` 体内 import） |
| `test_verification_modules_contract.py` | `hasattr` / `def` 承载断言 | `_run_three_stage_verification` 存在于 `pipeline.py` 且不重复 |
| `test_agent_runner_modules_contract.py` | `inspect.getsource` | `_execute_agent_inner` 源码含 `self._check_agent_result_artifact(`、不含 `result_gate.` |

> D7：模块级名（`subprocess` / `time` / `json` / `datetime` / `commit_wip_checkpoint`）MUST 保持可从 `core.agent_runner.runner` 访问且 patch 语义有效——新提取方法 MUST 仍在 `runner.py` 内以模块全局名引用。

---

## 5. 无未归属块声明

上述 B0–B10 与 R0–R9 共 20 块覆盖两个函数的全部源码（实测范围 B：L563–1819 的 1257 行；R：L1561–2586 的 1026 行），无遗留语句。循环体内（B2/B3、R4/R5/R6）以 D2 边界为准，可提取子段已在表中标注。

---

## 6. D4 Import 缝隙清点（MUST 保留在运行时函数体内）

`_run_three_stage_verification` 内有 6 个局部 import 点，测试靠 `patch("core.verify_engine.VerifyEngine")` 在 FakeEngine 生效的根基——extract 时 MUST 把这些 import 保留在运行时函数体内（D4），MUST NOT 上提为模块级。

### 6.1 局部 import 位置

| 块 | 行号 | import 语句 | 说明 |
|---|---|---|---|
| B0 | L578 | `import asyncio` | 阶段2 asyncio.run 调用 |
| B0 | L579 | `import importlib` | 模块热重载 |
| B0 | L580 | `import sys` | sys.modules 检查 |
| B0 | L635 | `from core.verify_engine import VerifyEngine` | 重载后导入最新版 |
| B0 | L636 | `from core.verify_engine.scenarios import load_scenarios` | 场景加载 |
| B2 | L925 | `from core.verify_contract import selfcheck_contract_light` | 循环体内契约轻量自检 |

### 6.2 依赖 `patch("core.verify_engine.VerifyEngine")` 的测试文件

以下测试文件在 `_run_three_stage_verification` 执行路径上依赖 patch `core.verify_engine.VerifyEngine` 为 FakeEngine：

| 测试文件 | patch 方式 | 说明 |
|---|---|---|
| `test_pm_verification.py` | `patch("core.verify_engine.VerifyEngine", FakeEngine)` | 多个场景：端口重写/inconclusive/不可达/全通过 |
| `test_pm_recovery.py` | 同上 | 恢复路径 |
| `test_planready_artifact_gate.py` | 同上 | 产物门测试 |
| `test_verdict_contamination.py` | 同上 | 裁决污染隔离 |
| `test_verdict_read_failclosed.py` | 同上 | 读取 fail-closed 路径 |
| `test_verdict_retry_misattribution.py` | 同上 | 重试归因 |
| `test_verify_parallel_backoff.py` | 同上 | 并行退避 |

**D4 阈值**：提取 B0 时，`VerifyEngine` / `load_scenarios` 的 `from` import MUST 跟随 `_reload_verify_engine_modules` 或 `_check_entry_status` 在运行时函数体内执行；若提取方法自身包含该段，import 留在该方法体内。MUST NOT 为此将 patch 改为 `core.pm_engine.verification.pipeline.VerifyEngine`。

---

## 7. D6 runner 行数契约（实测基线）

`tests/test_agent_runner_modules_contract.py` 的 `test_runner_below_4000`（L170-173）断言 `runner.py < 4000` 行。
重构前工作树实测 `runner.py = 3946` 行（< 4000，断言通过）。

| 项目 | 行数 |
|---|---|
| 重构前 runner.py 当前 | 3946 |
| 重构前合约上限（L170-173，断言 `n < 4000`） | 4000 |
| 重构前余量 | 54 行 |
| 阶段 4 提取新增（实测） | 347 行（私有方法 + 注释，含 `_maybe_in_place_retry` / `_handle_artifact_gate_retry` 等） |
| **重构后 runner.py 实测** | **4293** |
| **Task 5.7 修订上限（登记新值）** | **4500**（断言 `n < 4500`，余量 207 行） |

**裁决（D6）**：采用 (a)——新提取方法留在 `runner.py`，显式修订行数上限。阶段 4 Task 5.7 实施完成。

---

## 8. D7 模块级 patch 缝隙清点（语义保持基线）

### 8.1 runner 侧 patch 语义（`core.agent_runner.runner`）

以下测试文件对 `core.agent_runner.runner` 的模块级名做 patch / `setattr`，提取方法时 MUST 保持这些名字可从模块顶层访问：

| 测试文件 | patch 目标 | patch 方式 |
|---|---|---|
| `test_turn_limit_lifecycle.py` | `rmod.subprocess` | `setattr(rmod, "subprocess", ns)` |
| `test_impl_wip_checkpoint.py` | `runner_mod.commit_wip_checkpoint` | `setattr(runner_mod, "commit_wip_checkpoint", _boom)` |
| `test_main_tree_deps_provision.py` | `core.agent_runner.runner.*` | 模块级名替换 |
| `test_verify_command_port.py` | `core.pm_engine.verification.subprocess` | 模块级名替换 |
| `test_blocked_reverify_gate.py` | `core.pm_engine.verification.subprocess` | 模块级名替换 |
| `test_frozen_scenario_schema_migration.py` | `core.pm_engine.verification.*` | 模块级名替换 |

**D7 要求**：提取出的新方法 MUST 仍在 `runner.py` 内以模块全局名（`subprocess` / `time` / `json` / `datetime` / `commit_wip_checkpoint`）引用这些名字——MUST NOT 改为局部 import（否则 `setattr(rmod, "subprocess", ns)` patch 失效）。

### 8.2 pipeline 侧 patch 语义（`core.pm_engine.verification`）

| 测试文件 | patch 目标 |
|---|---|
| `test_verify_command_port.py` | `core.pm_engine.verification.subprocess` |
| `test_blocked_reverify_gate.py` | `core.pm_engine.verification.subprocess` |
| `test_frozen_scenario_schema_migration.py` | `core.pm_engine.verification.*` |

---

## 9. D5 契约测试处置清单

### 9.1 `test_verification_modules_contract.py`（verification 侧）

| 断言 | 挡路？ | 处置 |
|---|---|---|
| L48-55: `hasattr(VerificationPipeline, "_run_three_stage_verification")` | 否 | 保留，函数拆分为私有方法后该断言仍成立 |
| L89-108: `def _run_three_stage_verification(` 存在且未重复 | 否 | 保留，函数仍在 pipeline.py 且不重复 |
| 模块 docstring 第 4 条（"大函数仅搬移…内部不动"） | 过时 | Task 5.6 改写为「主函数收敛为编排骨架」，**新增**主函数收敛断言（MUST NOT 替换既有断言） |

### 9.2 `test_agent_runner_modules_contract.py`（runner 侧）

| 断言 | 挡路？ | 处置 |
|---|---|---|
| L170-173: `test_runner_below_4000` | **已修订**（重构后 4293 行已破 4000 上限） | Task 5.7 完成：上限修订为 `n < 4500` 并登记新值 |
| L179-184: `inspect.getsource(_execute_agent_inner)` 含 `self._check_agent_result_artifact(`、不含 `result_gate.` | **不挡路**（R4 只提戳拷回子段，产物门调用仍留在主函数） | 保留（D1 R4 口径下不被破坏）；若实现偏离口径把产物门移出主函数，MUST 改锚到提取方法 |

### 9.3 契约测试处置总结

- verification 侧：**无断言挡路**，仅同步过时 docstring + **已新增**收敛断言（Task 5.6 完成）
- runner 侧：`test_runner_below_4000` 已破上限，**上限已修订为 4500**（Task 5.7 完成）；`inspect.getsource` 断言不挡路、保留原样

---

## 10. 全量套件基线失败集合（Task 1.4，重构前）

入口：`python3 bin/run_full_suite.py --timeout 3600 --baseline HEAD`，elapsed≈190s（两次运行均无挂起，rc=1）。

当前失败清单（全部为存量失败，分类=存量，无新增）：

| 测试 | 基线同现 | 结论 |
|---|---|---|
| `test_dashboard_api.py::TestServerAPI::test_index_served` | 是 | 存量 |
| `test_dashboard_api.py::TestServerAPI::test_static_root_fallback_to_dist` | 是 | 存量 |
| `test_task_track.py::TestCliWarning::test_missing_tasks_md_silent` | 是 | 存量 |
| `test_task_track.py::TestCliWarning::test_parseable_tasks_md_no_warning` | 是 | 存量 |
| `test_task_track.py::TestCliWarning::test_undotted_format_still_parses` | 是 | 存量 |
| `test_task_track.py::TestCliWarning::test_unparseable_tasks_md_prints_warning` | 是 | 存量 |

> 基线侧另含 `test_callsite_arity_guard.py::TestArityGuardTeeth::test_node_modules_vendored_excluded`（当前侧未见——疑似环境相关，非本变更引入）。
>
> 关注序列均不在失败集：`test_pm_verification` / `test_pm_recovery` / `test_verdict_*` /
> `test_transient_backoff` / `test_agent_runner_gate` / `test_turn_limit_lifecycle` /
> `test_impl_wip_checkpoint` ——全部通过。

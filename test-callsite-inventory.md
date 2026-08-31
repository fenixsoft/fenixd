# tests/ 门面委托调用点盘点与分批迁移计划

## 1. 门面委托方法清单

### 1.1 PMEngine 门面 (core/pm_engine/engine.py)

#### Dispatcher 组件委托 (self._dispatcher)
- `_process_queue()` → `self._dispatcher.process_queue()`
- `_queue_lock` (property) → `self._dispatcher._queue_lock`
- `_run_queue` (property) → `self._dispatcher._run_queue`
- `_active_runs` (property) → `self._dispatcher._active_runs`
- `_active_priorities` (property) → `self._dispatcher._active_priorities`
- `_active_priority_counts` (property) → `self._dispatcher._active_priority_counts`
- `_backoff_timers` (property) → `self._dispatcher._backoff_timers`
- `_dispatch_backoff_schedule()` → `self._dispatcher._dispatch_backoff_schedule()`
- `_handle_dispatch_lock_conflict(spec_name)` → `self._dispatcher._handle_dispatch_lock_conflict(spec_name)`
- `_schedule_backoff_retry(spec_name, delay)` → `self._dispatcher._schedule_backoff_retry(spec_name, delay)`
- `_get_spec_priority(spec_name)` → `self._dispatcher._get_spec_priority(spec_name)`
- `_enqueue(spec_name, agent_type)` → `self._dispatcher._enqueue(spec_name, agent_type)`

#### FamilyGovernor 组件委托 (self._family)
- `_resolve_fix_spec_name(spec_name)` → `self._family._resolve_fix_spec_name(spec_name)`
- `_ensure_fix_spec_files(fix_spec_name, parent_spec_name)` → `self._family._ensure_fix_spec_files(...)`
- `_fix_prefix_depth(name)` → `self._family._fix_prefix_depth(name)`
- `_fix_strip_all(name)` → `self._family._fix_strip_all(name)`
- `_family_width(child_name)` → `self._family._family_width(child_name)`
- `_family_waiver_set(spec_name)` → `self._family._family_waiver_set(spec_name)`
- `_consume_family_waiver(spec_name)` → `self._family._consume_family_waiver(spec_name)`
- `_family_gate_blocked(parent_name, child_name)` → `self._family._family_gate_blocked(...)`
- `_is_fix_spec(name)` → `self._family._is_fix_spec(name)`
- `_same_root(name_a, name_b)` → `self._family._same_root(name_a, name_b)`
- `_same_root_siblings(spec_name)` → `self._family._same_root_siblings(spec_name)`
- `_sibling_repair_active(spec_name, my_enqueued_at)` → `self._family._sibling_repair_active(...)`
- `_sibling_has_live_agent(spec_name)` → `self._family._sibling_has_live_agent(spec_name)`
- `_has_non_terminal_child_fix(spec_name)` → `self._family._has_non_terminal_child_fix(spec_name)`
- `_signal_family_explosion(parent_name, child_name, detail)` → `self._family._signal_family_explosion(...)`
- `_do_spec_bug_found(spec_name)` → `self._family._do_spec_bug_found(spec_name)`
- `_do_legacy_fix_spec_bug_found(spec_name)` → `self._family._do_legacy_fix_spec_bug_found(spec_name)`
- `_inject_verify_fix_task(spec_name, fail_rounds)` → `self._family._inject_verify_fix_task(...)`
- `_send_human_escalation_alert(...)` → `self._family._send_human_escalation_alert(...)`

#### ImplBudget 组件委托 (self._budget)
- `_impl_run_budget()` → `self._budget._impl_run_budget()`
- `_increment_impl_run_budget_used(spec_name)` → `self._budget._increment_impl_run_budget_used(...)`
- `_budget_exempt_alert_threshold()` → `self._budget._budget_exempt_alert_threshold()`
- `_exempt_dead_run_budget(spec_name, reason)` → `self._budget._exempt_dead_run_budget(...)`
- `_alert_budget_exempt_loop(spec_name, exempt)` → `self._budget._alert_budget_exempt_loop(...)`
- `_reconcile_impl_budget(spec_name)` → `self._budget._reconcile_impl_budget(spec_name)`
- `_count_normal_completed_impl_runs(spec_name)` → `self._budget._count_normal_completed_impl_runs(...)`
- `_impl_run_budget_used(spec_name)` → `self._budget._impl_run_budget_used(spec_name)`
- `_check_impl_budget_exhausted(spec_name)` → `self._budget._check_impl_budget_exhausted(...)`

#### RecoveryWatch 组件委托 (self._recovery)
- `_recovery_watch` (property) → `self._recovery._recovery_watch`
- `_signal_fingerprints` (property) → `self._recovery._signal_fingerprints`
- `_save_recovery_watch()` → `self._recovery._save_recovery_watch()`
- `_clear_dispatch_conflict(spec_name)` → `self._recovery._clear_dispatch_conflict(spec_name)`

### 1.2 AgentRunner 门面 (core/agent_runner/runner.py)

#### PromptBuilder 组件委托 (self._prompt_builder)
- `_build_prompt(spec_name, agent_type, detail)` → `self._prompt_builder._build_prompt(...)`
- `_build_legacy_section(spec_name)` → `self._prompt_builder._build_legacy_section(spec_name)`
- `_legacy_dirty_snapshot(wt_path)` → `self._prompt_builder._legacy_dirty_snapshot(wt_path)`
- `_scenario_freeze_section(spec_name)` → `self._prompt_builder._scenario_freeze_section(spec_name)`
- `_interaction_contract_section(spec_name)` → `self._prompt_builder._interaction_contract_section(...)`
- `_triage_recheck_section(spec_name)` → `self._prompt_builder._triage_recheck_section(...)`
- `_verdict_rejection_section(spec_name)` → `self._prompt_builder._verdict_rejection_section(...)`

#### ProviderCircuit 组件委托 (self._provider_circuit)
- `provider_circuits` (property) → `self._provider_circuit.provider_circuits`
- `_daily_provider_attempts` (property) → `self._provider_circuit._daily_provider_attempts`
- `_daily_provider_warned` (property) → `self._provider_circuit._daily_provider_warned`
- `_daily_reset_date` (property) → `self._provider_circuit._daily_reset_date`
- `_circuit_state(provider_name)` → `self._provider_circuit._circuit_state(...)`
- `is_circuit_open(provider_name, now)` → `self._provider_circuit.is_circuit_open(...)`
- `is_switch_cooldown(provider_name, now)` → `self._provider_circuit.is_switch_cooldown(...)`
- `_record_switch_cooldown(provider_name, now)` → `self._provider_circuit._record_switch_cooldown(...)`
- `_write_provider_marker(...)` → `self._provider_circuit._write_provider_marker(...)`
- `_record_daily_provider_attempt(provider_name)` → `self._provider_circuit._record_daily_provider_attempt(...)`
- `_circuit_open_error(provider_name, now)` → `self._provider_circuit._circuit_open_error(...)`
- `_record_provider_4xx(provider_name, code, now)` → `self._provider_circuit._record_provider_4xx(...)`
- `_record_provider_probe(provider_name, success, now)` → `self._provider_circuit._record_provider_probe(...)`

#### LivenessSupervisor 组件委托 (self._liveness)
- `_liveness_snapshot(p, timeout)` → `self._liveness._liveness_snapshot(p, timeout)`
- `_pgrep_live_attempt(spec)` → `self._liveness._pgrep_live_attempt(spec)`

#### TokenAccountant 组件委托 (self._token_accountant)
- `_accumulate_token_usage(spec_name, usage_info)` → `self._token_accountant._accumulate_token_usage(...)`
- `_check_token_budget(spec_name, tokens_in)` → `self._token_accountant._check_token_budget(...)`
- `_send_token_alert(...)` → `self._token_accountant._send_token_alert(...)`
- `_record_verify_progress_tokens(...)` → `self._token_accountant._record_verify_progress_tokens(...)`
- `_extract_usage_info(event)` → `self._token_accountant._extract_usage_info(event)`

#### V2ServerManager 组件委托 (self._v2_server)
- `_v2_ensure_state()` → `self._v2_server._v2_ensure_state()`
- `_v2_launch_for_worktree(wt_path)` → `self._v2_server._v2_launch_for_worktree(...)`
- `_v2_inject_env(wt_path)` → `self._v2_server._v2_inject_env(wt_path)`
- `_v2_stop_for_worktree(wt_path)` → `self._v2_server._v2_stop_for_worktree(...)`
- `_v2_stop_all()` → `self._v2_server._v2_stop_all()`

#### SessionTracker 组件委托 (self._session)
- `_clear_admin_disposition()` → `self._session._clear_admin_disposition()`

## 2. 测试文件调用点统计

| 测试文件 | 调用点数 | 主要涉及组件 |
|---------|---------|-------------|
| test_core.py | 287 | 混合（dispatcher, family, budget, recovery, verification, reporting） |
| test_fail_counter_budget.py | 58 | budget, family |
| test_repair_lane_dedup.py | 47 | family |
| test_provider_circuit.py | 43 | provider_circuit |
| test_admin.py | 40 | session, provider_circuit |
| test_dispatch_aging.py | 36 | dispatcher |
| test_run_lifecycle_governance.py | 35 | dispatcher, liveness, recovery |
| test_family_governor.py | 35 | family |
| test_provider_failover.py | 29 | provider_circuit |
| test_env_sanity_gate.py | 20 | verification |
| test_characterization_split.py | 20 | verification |
| test_cost_observability.py | 18 | token_accountant |
| test_agent_runner.py | 16 | prompt_builder, liveness |
| test_repair_redispatch.py | 15 | family, dispatcher |
| test_deliverable_gate.py | 12 | verification |
| test_inplace_bug_repair.py | 11 | family |
| test_verdict_evidence_taxonomy.py | 7 | verification |
| test_recovery_legacy.py | 7 | recovery |
| test_verify_report_gate.py | 5 | verification |
| test_interaction_contract.py | 4 | verification |
| test_alert_lifecycle.py | 4 | recovery |
| test_pm_engine_dispatch_fixes.py | 3 | dispatcher |
| test_worktree_merge_guard.py | 0 | - |
| test_verify_scenarios.py | 0 | - |
| test_v2_dev_server.py | 0 | - |
| test_spec_gen.py | 0 | - |
| test_dashboard.py | 0 | - |

## 3. 分批迁移计划

按组件耦合面从小到大分批，test_core.py 最后迁移。

### 批次 1: 单组件测试文件（耦合面最小）
**文件列表：**
- test_provider_circuit.py (43 调用点) → provider_circuit
- test_cost_observability.py (18 调用点) → token_accountant
- test_dispatch_aging.py (36 调用点) → dispatcher
- test_family_governor.py (35 调用点) → family
- test_fail_counter_budget.py (58 调用点) → budget, family

**迁移目标：**
- `runner._xxx` → `runner._provider_circuit.xxx` (provider_circuit)
- `runner._xxx` → `runner._token_accountant.xxx` (token_accountant)
- `engine._xxx` → `engine._dispatcher.xxx` (dispatcher)
- `engine._xxx` → `engine._family.xxx` (family)
- `engine._xxx` → `engine._budget.xxx` (budget)

### 批次 2: agent_runner 侧测试文件
**文件列表：**
- test_agent_runner.py (16 调用点) → prompt_builder, liveness
- test_provider_failover.py (29 调用点) → provider_circuit
- test_run_lifecycle_governance.py (35 调用点) → dispatcher, liveness, recovery
- test_admin.py (40 调用点) → session, provider_circuit

**迁移目标：**
- `runner._xxx` → `runner._prompt_builder.xxx` (prompt_builder)
- `runner._xxx` → `runner._liveness.xxx` (liveness)
- `runner._xxx` → `runner._session.xxx` (session)
- `engine._xxx` → `engine._dispatcher.xxx` (dispatcher)
- `engine._xxx` → `engine._recovery.xxx` (recovery)

### 批次 3: 验证链路测试文件
**文件列表：**
- test_verify_report_gate.py (5 调用点) → verification
- test_verify_scenarios.py (0 调用点) → verification
- test_verdict_evidence_taxonomy.py (7 调用点) → verification
- test_interaction_contract.py (4 调用点) → verification
- test_deliverable_gate.py (12 调用点) → verification
- test_env_sanity_gate.py (20 调用点) → verification
- test_characterization_split.py (20 调用点) → verification
- test_inplace_bug_repair.py (11 调用点) → family

**迁移目标：**
- `engine._xxx` → `engine._verification.xxx` (verification)
- `engine._xxx` → `engine._family.xxx` (family)

### 批次 4: test_core.py（最后迁移，耦合面最大）
**文件列表：**
- test_core.py (287 调用点) → 混合所有组件

**迁移目标：**
- 按上述组件分类逐个迁移

### 批次 5: 残余文件（扫尾）
**文件列表：**
- test_dashboard.py (0 调用点)
- test_alert_lifecycle.py (4 调用点) → recovery
- test_recovery_legacy.py (7 调用点) → recovery
- test_repair_lane_dedup.py (47 调用点) → family
- test_repair_redispatch.py (15 调用点) → family, dispatcher
- test_pm_engine_dispatch_fixes.py (3 调用点) → dispatcher

**迁移目标：**
- `engine._xxx` → `engine._recovery.xxx` (recovery)
- `engine._xxx` → `engine._family.xxx` (family)
- `engine._xxx` → `engine._dispatcher.xxx` (dispatcher)

## 4. 迁移规则

### 4.1 迁移原则
1. **语义等价**：只改调用点写法，不改测试用例的行为预期
2. **分批提交**：每批独立 commit，批内先改写后验证
3. **最小改动**：diff 仅含测试调用点改写，不含断言值、夹具构造或场景逻辑的修改

### 4.2 迁移示例

#### Dispatcher 组件
```python
# 迁移前
engine._process_queue()
engine._enqueue(spec_name, "implementer")
engine._schedule_backoff_retry(spec_name, delay)

# 迁移后
engine._dispatcher.process_queue()
engine._dispatcher._enqueue(spec_name, "implementer")
engine._dispatcher._schedule_backoff_retry(spec_name, delay)
```

#### FamilyGovernor 组件
```python
# 迁移前
engine._do_spec_bug_found(spec_name)
engine._fix_prefix_depth(name)
engine._family_width(child_name)

# 迁移后
engine._family._do_spec_bug_found(spec_name)
engine._family._fix_prefix_depth(name)
engine._family._family_width(child_name)
```

#### ImplBudget 组件
```python
# 迁移前
engine._impl_run_budget()
engine._increment_impl_run_budget_used(spec_name)
engine._check_impl_budget_exhausted(spec_name)

# 迁移后
engine._budget._impl_run_budget()
engine._budget._increment_impl_run_budget_used(spec_name)
engine._budget._check_impl_budget_exhausted(spec_name)
```

#### ProviderCircuit 组件
```python
# 迁移前
runner._circuit_state(provider_name)
runner._record_provider_4xx(provider_name, code, now)
runner._record_daily_provider_attempt(provider_name)

# 迁移后
runner._provider_circuit._circuit_state(provider_name)
runner._provider_circuit._record_provider_4xx(provider_name, code, now)
runner._provider_circuit._record_daily_provider_attempt(provider_name)
```

#### PromptBuilder 组件
```python
# 迁移前
runner._build_prompt(spec_name, agent_type, detail)
runner._build_legacy_section(spec_name)

# 迁移后
runner._prompt_builder._build_prompt(spec_name, agent_type, detail)
runner._prompt_builder._build_legacy_section(spec_name)
```

#### LivenessSupervisor 组件
```python
# 迁移前
runner._liveness_snapshot(p, timeout)
runner._pgrep_live_attempt(spec)

# 迁移后
runner._liveness._liveness_snapshot(p, timeout)
runner._liveness._pgrep_live_attempt(spec)
```

#### TokenAccountant 组件
```python
# 迁移前
runner._accumulate_token_usage(spec_name, usage_info)
runner._check_token_budget(spec_name, tokens_in)
runner._extract_usage_info(event)

# 迁移后
runner._token_accountant._accumulate_token_usage(spec_name, usage_info)
runner._token_accountant._check_token_budget(spec_name, tokens_in)
runner._token_accountant._extract_usage_info(event)
```

## 5. 验证策略

### 5.1 批次验证
- 每批迁移后，运行该批文件的 pytest 单跑通过
- 每批迁移后，运行全量 pytest 通过

### 5.2 最终验证
- 全量 pytest 结果不劣于基线（912 passed + 1 环境性失败）
- grep 确认 tests/ 中不再有指向已删委托的调用

### 5.3 门面收缩验证
- grep 全仓库确认零调用者后才删除委托方法
- fenixd.py 与 core/dashboard 的 import 及调用语句无任何修改

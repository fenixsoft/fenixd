# Tasks: refactor-agent-runner-module

## Deliverables

```yaml
- path: core/agent_runner/result_gate.py
  kind: new
- path: core/agent_runner/maintenance_runs.py
  kind: new
- path: core/agent_runner/latency.py
  kind: new
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/__init__.py
  kind: modify
- path: tests/test_characterization_agent_runner.py
  kind: new
- path: tests/test_agent_runner_modules_contract.py
  kind: new
- path: tests/helpers.py
  kind: modify
- path: tests/test_agent_runner_gate.py
  kind: modify
- path: tests/test_planready_artifact_gate.py
  kind: modify
- path: tests/test_worktree_reuse.py
  kind: modify
- path: tests/test_verdict_contamination.py
  kind: modify
- path: tests/test_run_lifecycle_hardening.py
  kind: modify
- path: tests/test_transient_backoff.py
  kind: modify
- path: tests/test_provider_failover.py
  kind: modify
- path: tests/test_retry_orphan_active_runs.py
  kind: modify
- path: tests/test_run_cancel.py
  kind: modify
- path: tests/test_verdict_dedup_resynthesis.py
  kind: modify
- path: spec/changes/refactor-agent-runner-module/contract-inventory.md
  kind: new
- path: spec/changes/refactor-agent-runner-module/agent-runner-findings.md
  kind: new
```

> 说明：`tests/test_fast_track_scale_precheck.py` 与 `tests/test_turn_limit_lifecycle.py` **不在交付集**——`_run_claude` 保留在 `runner.py`（design D1），其 `subprocess` 补丁缝隙不发生迁移，两文件 MUST NOT 修改。
> 上述 11 个 `kind: modify` 的测试文件对应 design D5 的测试缝 setter 收敛。

## 1. 阶段 0：测试基线加固

- [x] 1.1 静态清点：提取 `runner.py` 的**全部顶层名字**（模块级函数、常量、导入名）与 `AgentRunner` 的方法名清单，落盘 `contract-inventory.md`；MUST 覆盖 design D6 的补丁缝隙清单（`subprocess` / `commit_wip_checkpoint` / `LATENCY_STALL_SECONDS` / `_PLANNER_SEMAPHORE` / `_PLANNER_SEMAPHORE_LIMIT` / 五个结果与异常类）
- [x] 1.2 补 characterization tests（`tests/test_characterization_agent_runner.py`）：锁定 `AgentRunResult` / `AdminDisposition` / `SelfReviewResult` / `EvolutionResult` 的构造与 `to_dict` 字段；锁定 `_check_artifact_json_file` / `_check_agent_result_artifact` / `_check_impl_result_artifact` / `_check_success_completion` / `_check_partial_consistency` 的判定行为
- [x] 1.3 建立疑点清单（`agent-runner-findings.md`），持续维护只记录不修
- [x] 1.4 运行 `bin/run_full_suite.py` 记录重构前基线失败集合（重点 `test_agent_runner*`、`test_fast_track_scale_precheck`、`test_turn_limit_lifecycle`、`test_run_cancel`、`test_run_latency_stats`）
- [x] 1.5 记录 D6 补丁缝隙的三个 patch 调用点为「不得失效」基线：`tests/test_fast_track_scale_precheck.py:459-470`、`tests/test_turn_limit_lifecycle.py:182-217`、`tests/test_run_cancel.py` 的 `runner_module.subprocess.Popen` 替换

## 2. 阶段 1：提取无状态模块

- [x] 2.1 提取 `core/agent_runner/result_gate.py`：迁四个结果类、`AgentArtifactGateError`、`RunCancelledError`，以及 `_check_artifact_json_file` / `_check_agent_result_artifact` / `_check_impl_result_artifact` / `_check_success_completion` / `_check_partial_consistency` / `_check_taskupdate_crosscheck` / `_format_gap_list` / `_invalid_completed_ids` / `_read_init_tools` / `_append_crosscheck_skipped`
- [x] 2.2 提取 `core/agent_runner/latency.py`：迁 `iter_events` / `_entry_is_tool_result` / `latency_samples_from_events` / `latency_stats` / `_percentile` / `format_latency_summary`，**并一并迁移 `LATENCY_STALL_SECONDS`**（防循环 import）；`_default_ts_parser` 按 design D4 修订版处理——`latency.py` 自带等价实现（MUST NOT 回引 `runner`），`runner.py` 保留同名模块级函数并一行委托，`AgentRunner._parse_event_timestamp` 留在原位
- [x] 2.3 `runner.py` 对上述符号保留 re-export（含 `LATENCY_STALL_SECONDS` 与四个 latency 函数——`bin/analyze_run_latency.py:33-35` 亦从 `runner` 导入），`core/agent_runner/__init__.py` 补齐导出；MUST NOT 改动 `_run_claude` 及其同域辅助
- [x] 2.3b 按 design D2b 规则 1/3 注入门面依赖并同迁常量：产物门函数以 `runner` 参数接收 `logger` / `project_root` / `_IMPL_RESULT_STATUSES`；`_ARTIFACT_FRESHNESS_GRACE_SECONDS` / `_PLANREADY_STATUSES` 随迁 `result_gate.py` 并由 `runner.py` re-export；`DEFAULT_GATEWAY_MODEL` / `admin_disposition_path` 随迁 `maintenance_runs.py` 并由 `runner.py` re-export；提取模块 MUST NOT `import runner`
- [x] 2.3c 内部调用点 MUST 继续经委托调用：`runner.py:2803` / `:4345` / `:4493` / `:4502` / `:4639` 等处的 `self.<方法名>(...)` MUST NOT 改写为直呼新模块函数（否则实例属性打桩静默失效：`tests/test_worktree_reuse.py:194`、`test_provider_circuit.py:50`、`test_review_circuit_breaker.py:360`、`test_run_lifecycle_hardening.py:742`、`test_provider_failover.py:86`）
- [x] 2.4 全量 pytest + import 校验（含反向导入校验：单独 `import core.agent_runner.result_gate` / `latency` 不触发循环），独立 commit

## 3. 阶段 2：提取维护型 run

- [x] 3.1 提取 `core/agent_runner/maintenance_runs.py`：迁 `run_administrator` / `run_self_review` / `run_evolution` 及其配套 `_clear/_delete/_read_admin_disposition`、`_clear/_delete/_read_self_review_out`、`_accumulate_self_review_tokens`、`_delete_evolution_out`、`_accumulate_evolution_tokens`、`_get_admin_model`；各函数以 `runner` 显式参数接收门面依赖（`_get_admin_model` 实测依赖 `self._get_config` 与 `DEFAULT_GATEWAY_MODEL`，非「无 self 依赖」）
- [x] 3.2 `AgentRunner` 对上述方法保留一行委托（保持测试调用路径与签名，含关键字参数）
- [x] 3.3 全量 pytest（重点 `test_admin.py`、`test_self_evolution.py`、`test_daily_self_review.py`）+ import 校验，独立 commit

## 4. 阶段 3：测试缝转发属性收敛

- [x] 4.1 删除 8 组转发属性的 setter/deleter（`provider_circuits` / `_daily_provider_attempts` / `_daily_provider_warned` / `_daily_reset_date` / `_v2_servers` / `_v2_used_ports` / `_v2_run_seq` / `_extension_baselines`），保留 getter 且保持「组合对象缺失时惰性创建」；**同步改写生产内部写点 `runner.py:3917`**（`_check_daily_limit` 内 `self._daily_reset_date = today` → `self._provider_circuit._daily_reset_date = today`），否则主链路派发（`runner.py:2505`）在 setter 删除后抛 `AttributeError`
- [x] 4.2 改写 D5 的 11 个测试文件中的赋值点（`runner.<名> = v` → 替换组合对象属性）；逐一确认对应测试仍通过
- [x] 4.3 全量 pytest（重点 `test_daemon_lifecycle_races`、`test_provider_circuit`、`test_provider_failover`、`test_run_lifecycle_hardening`）+ 独立 commit

## 5. 阶段 4：runner 收尾、docstring 修复与契约核对

- [x] 5.1 修复 `_run_claude` 的 docstring 位置（把函数体内 `from core.config import ConfigLoader` 移至首段逻辑之后），确认 `ast.get_docstring()` 返回非 None
- [x] 5.2 清理残余空壳与不再需要的 import；确认 `runner.py` 行数 ≤ 3800
- [x] 5.3 运行 `tests/test_agent_runner_modules_contract.py`：验证 D6 全部名字可从 `runner` 访问、结果类 re-export 同一对象、`_run_claude` 补丁缝隙可用、8 组 setter/deleter 已删、行数上限；并补三条断言——(a) `runner._check_agent_result_artifact = MagicMock()` 实例打桩后 `_execute_agent_inner` 路径实际使用该替身（委托未被绕过）；(b) `DEFAULT_GATEWAY_MODEL` / `admin_disposition_path` / `_PLANREADY_STATUSES` / `_ARTIFACT_FRESHNESS_GRACE_SECONDS` 经 `runner` 可访问且与其新模块来源同一对象；(c) 单独 `import core.agent_runner.result_gate` / `maintenance_runs` / `latency` 不触发循环 import，且 `latency._default_ts_parser` 与 `runner.AgentRunner._parse_event_timestamp` 对同一样本返回一致
- [x] 5.4 全量 pytest 全绿（相对基线无新失败），独立 commit

## 6. 阶段 5：收尾验证

- [ ] 6.1 全量 `bin/run_full_suite.py`（**必须全量回归，不得只跑子集**）+ 全部 import 路径验证 + 疑点清单最终汇报（向用户汇报，代码不动）
- [ ] 6.2 经用户确认时机后 `touch .fenix/restart_request` 重启 daemon 并冒烟验证（重构收尾前不得重启）

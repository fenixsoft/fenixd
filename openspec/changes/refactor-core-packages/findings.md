# findings: refactor-core-packages

本文档自阶段 0 起持续维护，承载两部分：

1. **覆盖分析清单**（任务 1.1）：将被搬移方法的无覆盖情况与 characterization tests 对应关系；
2. **疑点清单**（任务 1.3 / design D6）：拆分过程中发现的 bug / 死代码 / 可疑逻辑——只记录不修，
   代码保持行为等价，阶段 8 统一汇报。

---

## 1. 覆盖分析清单（阶段 0，任务 1.1）

基线口径：`python3 -m pytest tests/ --cov=core.agent_runner --cov=core.pm_engine`
（2026-08-31，含 tests/v2 之外的 27 个测试文件，基线 980 passed + 1 环境性失败）。

### 1.1 agent_runner.py（→ core/agent_runner/ 包）

将被搬移的方法（PromptBuilder / ProviderCircuit / TokenAccountant / V2ServerManager /
LivenessSupervisor / SessionTracker / run_files）**均有测试覆盖，无零覆盖搬移方法**。
仅有覆盖的方法：`AgentRunner.__init__`（9 行未覆盖，属构造分支）、`AgentRunResult.to_dict`
（13/15 行未覆盖——非搬移对象，保留在门面模块，不补测）。

### 1.2 pm_engine.py（→ core/pm_engine/ 包）

零覆盖且将被搬移的方法（已全部补 characterization tests，见
`tests/test_characterization_split.py`）：

| 方法 | 目标组件 | characterization |
|---|---|---|
| `_same_root` | FamilyGovernor | TestSameRootCharacterization |
| `_sibling_has_live_agent` | FamilyGovernor | TestSiblingHasLiveAgentCharacterization |
| `_rewrite_scenario_port` | VerificationPipeline | TestRewriteScenarioPortCharacterization |
| `generate_report` | ReportBuilder | TestReportingCharacterization |
| `generate_daily_report` | ReportBuilder | TestReportingCharacterization |
| `get_pushable_specs` | ReportBuilder | TestReportingCharacterization |
| `_signal_push_failed` | ReportBuilder | TestReportingCharacterization |
| `get_health_summary` | ReportBuilder | TestReportingCharacterization |
| `_dependencies_satisfied` | ReportBuilder | TestDependenciesSatisfiedCharacterization |

零覆盖但**不搬移**的方法（留在门面，事件回调编排职责，不属本清单补测范围）：
`_on_spec_drafted`、`_on_spec_implemented`、`_on_spec_bug_found`。

部分覆盖（存在未覆盖分支但主体被测）的将搬移方法不在阶段 0 补测范围
（任务书限定「无测试覆盖」口径），其已覆盖路径由既有测试锁定。

## 2. 疑点清单（阶段 0 起持续维护，只记录不修）

格式：`[阶段] 位置 — 现象 / 可疑点（结论留待阶段 8 汇报）`。

- [阶段 2] `core/agent_runner/provider_circuit.py` — 常量 `PROVIDER_CIRCUIT_PROBE_SUCCESS_CODE = 0`
  定义后无任何引用（全仓 grep 仅剩 runner.py 的转导 import）。半开探针的成功判据实际是
  「_run_claude 不抛异常即闭合」（见 `_execute_agent` 成功路径的 `_record_provider_probe`），
  该常量是 spec 落地时的残留命名。死代码，行为无影响。
- [阶段 3] `core/agent_runner/runner.py:66-70` — `V2_TEST_PORT_BASE` / `V2_TEST_PORT_RANGE` /
  `V2_DEV_SERVER_MARKER` 在门面重复定义（真源为 `core/v2_dev_server.py`，包内 v2_server.py
  与测试均从真源取用）。属死副本，保留仅因 `from core.agent_runner import *` 的历史兼容面；
  实际无人从 agent_runner 导入这三个名字。
- [阶段 6] `core/pm_engine/engine.py` — 常量 `DEFAULT_READY_STALL_THRESHOLD_MINUTES` 保留门面
  （其唯一消费者 `_ready_stall_threshold_minutes` 属假就绪巡检的阻塞项检测，留在门面
  check_blockers 域），与同注释块的其余常量（已随 RecoveryWatch 迁移）分离。
- [阶段 4/6 归属修正] 阶段 0 覆盖分析表中将 `_signal_push_failed` / `get_health_summary` /
  `_dependencies_satisfied` 预列为 ReportBuilder 搬移对象；实际实现中三者随 push 闸门与
  check_blockers 阻塞项检测留在门面（design D2 对 reporting.py 的界定为
  「项目报告/日报/pushable specs」，不含 push 信号与阻塞项）。characterization tests
  经门面调用，覆盖不受影响。

## 3. 阶段 7 审查结论（任务 8.1）

`core/worktree_manager.py`（1386 行）与 `core/admin_monitor.py`（1003 行）均为单一职责类、
无 TODO/FIXME、编译干净，体量远低于触发本次拆分的巨文件阈值（pm_engine 4879 / agent_runner
3068 行）。未发现明显坏味道，按任务书「预期改动极小或为零」执行**零改动**，无独立 commit。

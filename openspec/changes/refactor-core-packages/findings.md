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

- （暂无——各阶段拆分中发现后逐条追加于此）

# 验证报告：fix-frozen-scenario-orphan-reservoir

> ⚠️ 本报告由框架于 2026-09-09T12:27:17Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 6.88M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| write-gate-reject-illegal-scenario | 写端 schema 门拦截：补齐/收编路径写入缺少 kind 的非法条目时，validate_scenario_dicts 返回错误，该条目不落盘。出处：core/verify_engine/scenarios.py validate_scenario_dicts（D1 单一来源） | pass | 0/3 | - |
| write-gate-legal-scenario-passes | 写端 schema 门放行：场景列表全部通过结构校验（含 id/kind/steps/assertions 必填字段）时返回空错误清单，合法内容可正常落盘。出处：core/verify_engine/scenarios.py validate_scenario_dicts | pass | 0/3 | - |
| write-gate-single-source-validation | 三文件写入共用同一校验：load_scenarios 内部复用 validate_scenario_dicts，四个写入点也共用该函数，不存在绕过校验的写入路径。出处：core/verify_engine/scenarios.py:658 load_scenarios 调用 validate_scenario_dicts | pass | 0/2 | - |
| write-gate-backup-unrecoverable-drop | 补齐占位改弃场景：无理由缺失场景且 _scenarios_full.json 备份缺完整定义时，不再写 {'id','description'} 非法占位，登记「定义不可恢复」从本轮验证集剔除。出处：core/pm_engine/verification.py:797-812（通过 pytest TestReconcileUnrecoverableDrop 验证） | pass | 0/2 | - |
| write-gate-backup-available-restore | 补齐路径备份有完整定义时正常补回：无理由缺失场景 X 且备份存在 X 的完整合法定义时，X 从备份补回 test_scenarios.json，验证集完整。出处：core/pm_engine/verification.py:798-801（通过 pytest TestReconcileUnrecoverableDrop 验证） | pass | 0/2 | - |
| write-gate-backup-not-polluted | _scenarios_full.json 备份门：planner 产出含非法条目时备份不更新（存毒即失去可恢复价值），保留旧备份并留痕；全部合法时才更新备份。出处：core/pm_engine/verification.py:752-768（通过 pytest TestApplyScenarioFreezeSchemaGate 验证） | pass | 0/2 | - |
| load-purge-orphan-entries | 持久化集加载净化：scenarios.json 存在仅含 id/description 无 kind 的孤儿条目时，load_scenario_set 返回的集合不含这些条目。出处：core/verify_scenarios.py:173-189 load_scenario_set | pass | 0/3 | - |
| load-purge-no-file-mutation | 净化不污染原文件：加载净化发生剔除后 scenarios.json 原文件内容不被加载过程改写（净化只影响内存集合，文件修正由写端门与清理任务负责）。出处：core/verify_scenarios.py:157-188 load_scenario_set | pass | 0/2 | - |
| replan-same-errors-refuse-rerun | 重跑消费硬门：本轮错误清单与上轮完全相同（一字不差）时 _replan_errors_unconsumed 判 True（planner 未消费反馈），拒绝重跑走升级。出处：core/pm_engine/verification.py:1860-1868 _replan_errors_unconsumed | pass | 0/2 | - |
| replan-superset-errors-refuse-rerun | 重跑消费硬门超集判定：本轮错误清单为上轮错误的超集（上轮错误全部复现）时同样判定未消费反馈拒绝重跑。出处：core/pm_engine/verification.py:1860-1868 _replan_errors_unconsumed | pass | 0/2 | - |
| replan-reduced-errors-allow-rerun | 错误实质性消除允许预算内重跑：本轮错误数少于上轮（如 8 错降至 2 错）时 _replan_errors_unconsumed 判 False，允许在剩余重排预算内继续重跑。出处：core/pm_engine/verification.py:1860-1868 | pass | 0/2 | - |
| load-set-repairs-scenarios-json | 写端 schema 门下 save_scenario_set 剔除非法条目后落盘：含非法 kind 条目的场景集写回 scenarios.json 时坏条目被剔除，合法条目照常写入。出处：core/verify_scenarios.py:240-270 save_scenario_set | pass | 0/2 | - |
| replan-escalate-admin-not-human | 消费门拒绝后升级 admin 而非人工：planner 未消费反馈判定后 spec 置 blocked 并自动派发 admin 处置 run，首轮不产生人工升级告警（告警 severity=warning 而非 critical 人工级）。出处：core/pm_engine/verification.py:2198-2266 _escalate_env_blocked | pass | 0/4 | - |
| replan-two-rounds-freeze-human-with-cost | 两轮未修复后冻结升级人工并附成本：_escalate_env_blocked 连续 2 轮阻塞时 spec 结构化冻结（frozen=True）并升级人工，告警 severity=critical、处置选项标注重付出题成本。出处：core/pm_engine/verification.py:2208-2284 | pass | 0/4 | - |
| replan-admin-fix-recover-flow | admin 修复后重验通过恢复流转：验收通过时 _env_block_rounds 归零并解除阻塞（修复轮恢复正常状态机流转）。出处：core/pm_engine/verification.py:1636,2132 验收通过清零 _env_block_rounds（通过 pytest 既有验收路径覆盖） | pass | 0/2 | - |
| admin-prompt-contains-gate-constraints | admin 处置 prompt 含双约束：prompt_builder 生成的 admin 处置指令段声明「修复写回必须过结构校验」与「test_scenarios.json 与 scenarios.json 同源坏条目同步清理（双文件一致性）」。出处：core/agent_runner/prompt_builder.py:239-261 _admin_scenario_fix_constraints | pass | 0/3 | - |
| admin-cleanup-dual-file-consistent | admin 清理保持双文件一致：test_scenarios.json 移除孤儿条目时 scenarios.json 同源条目被同步移除（写端 schema 门在两文件各自剔除非法条目），双文件均无孤儿残留。出处：core/agent_runner/prompt_builder.py:256-258 admin 处置约束段 + core/verify_scenarios.py:240-270 save_scenario_set | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 17 个（第 1 轮）。

- 首轮写入 17 个场景


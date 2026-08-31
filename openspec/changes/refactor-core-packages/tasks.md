# Tasks: refactor-core-packages

## 1. 阶段 0：测试基线加固

- [x] 1.1 coverage 分析：识别将被搬移且无测试覆盖的 PMEngine/AgentRunner 方法清单
- [x] 1.2 为无覆盖的将搬移方法补 characterization tests（独立 commit，不改现有测试文件）
- [x] 1.3 建立疑点清单文件（自本阶段起持续维护，发现的 bug/死代码只记录不修）

## 2. 阶段 1：agent_runner → PromptBuilder

- [x] 2.1 提取 prompt_builder.py（_build_prompt + 各 section，保持文件读取时机等价：不缓存、不提前读取）
- [x] 2.2 门面委托：runner 侧保留 `_build_prompt` 等测试引用方法的一行委托
- [x] 2.3 全量 pytest 全绿 + import 验证通过，独立 commit

## 3. 阶段 2：agent_runner → 独立状态组件

- [ ] 3.1 提取 provider_circuit.py（provider_circuits 状态同迁；熔断/冷却/探针/4xx 记录；门面保留 `_record_provider_4xx` 等委托）
- [ ] 3.2 提取 token_budget.py（用量累计/预算检查/告警）
- [ ] 3.3 提取 v2_server.py（per-run 隔离测试服务器状态同迁）与 run_files.py（append_run_line/append_run_error/clean_old_runs 模块级函数，`__init__.py` 导出 clean_old_runs）
- [ ] 3.4 全量 pytest 全绿 + import 验证通过，独立 commit

## 4. 阶段 3：agent_runner 包成型

- [ ] 4.1 提取 liveness.py（存活检测/判活/超时监督/wait_for_running_agents）与 session.py（resumable session id 提取；体量过小可并入 runner.py）
- [ ] 4.2 建立 core/agent_runner/ 包结构：runner.py 门面组装组件，`__init__.py` 导出 AgentRunner/AgentRunResult/AdminDisposition/clean_old_runs
- [ ] 4.3 删除旧 core/agent_runner.py；`python -c` 逐一验证 import 路径与符号；全量 pytest 全绿，独立 commit

## 5. 阶段 4：pm_engine → FamilyGovernor + ImplBudget

- [ ] 5.1 提取 family.py（fix 家族治理/sibling repair/爆炸信号/waiver 状态同迁）
- [ ] 5.2 提取 budget.py（run 预算/豁免/告警/对账）
- [ ] 5.3 全量 pytest 全绿 + import 验证通过，独立 commit

## 6. 阶段 5：pm_engine → VerificationPipeline

- [ ] 6.1 提取 verification.py（三阶段+legacy 验证/冻结/合同/verdict evidence/交付物门/env blocked 处理；回引规则改写跨域调用）
- [ ] 6.2 门面委托：`_run_three_stage_verification`、`_run_legacy_verification`、`_apply_scenario_freeze`、`_handle_env_blocked_inconclusive` 等测试引用方法保持调用路径
- [ ] 6.3 全量 pytest 全绿（重点 test_verify_report_gate/test_verify_scenarios/test_verdict_evidence_taxonomy/test_interaction_contract）+ import 验证，独立 commit

## 7. 阶段 6：pm_engine 包成型

- [ ] 7.1 提取 dispatch.py（`_queue_lock` 与 `_run_queue`/`_active_runs`/`_active_priorities` 整体同迁，单锁验证）
- [ ] 7.2 提取 recovery.py 与 reporting.py
- [ ] 7.3 建立 core/pm_engine/ 包结构：engine.py 门面组装组件与事件回调编排，`__init__.py` 导出 PMEngine
- [ ] 7.4 删除旧 core/pm_engine.py；逐一验证 import；跑 test_dispatch_aging/test_repair_redispatch/test_repair_lane_dedup/test_pm_engine_dispatch_fixes 及全量 pytest，独立 commit

## 8. 阶段 7：轻梳理

- [ ] 8.1 审查 worktree_manager.py 与 admin_monitor.py，仅明显坏味道才做轻梳理（预期改动极小或为零），改动则独立 commit

## 9. 阶段 8：收尾验证

- [ ] 9.1 全量 pytest + 全部 import 路径验证 + 疑点清单最终汇报（向用户汇报，代码不动）
- [ ] 9.2 经用户确认时机后 touch `.fenix/restart_request` 重启 daemon 并冒烟验证（重构期间此前不得重启）

## 10. 阶段 9（可选，第二轮）

- [ ] 10.1 测试迁移清理（engine._xxx → 组件直调），单独 commit

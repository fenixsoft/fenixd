# Tasks: refactor-long-functions

## Deliverables

```yaml
- path: core/pm_engine/verification/pipeline.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_characterization_long_functions.py
  kind: new
- path: tests/test_verification_modules_contract.py
  kind: modify
- path: tests/test_agent_runner_modules_contract.py
  kind: modify
- path: spec/changes/refactor-long-functions/contract-inventory.md
  kind: new
- path: spec/changes/refactor-long-functions/long-function-findings.md
  kind: new
```

> `tests/test_verification_modules_contract.py` 与 `tests/test_agent_runner_modules_contract.py` 的 `kind: modify` 仅限 design D5/D6 的范围：前者仅同步过时的模块 docstring 表述并可**新增**「主函数收敛」断言（实测无断言挡路）；后者仅修订 `runner.py` 行数上限（D6），除非实现把产物门移出主函数，否则 MUST NOT 改动其 `inspect.getsource` 断言。MUST NOT 借机删除、替换或削弱任何既有断言。

## 1. 阶段 0：测试基线加固

- [ ] 1.1 静态清点：用 AST 提取 `_run_three_stage_verification` 与 `_execute_agent_inner` 的**全部分块**与局部变量清单（含粘合变量、写点、跨块读取），逐块落位到 design D1 分块表（pipeline 10 块 / runner 10 块），落盘 `contract-inventory.md`，**不留未归属块**
- [ ] 1.2 补 characterization tests（`tests/test_characterization_long_functions.py`）：锁定两个函数在当前代码上的可观测行为——状态推进序列、写出的产物内容、返回结构、异常类型与消息；在**拆分前**运行并记录基线结果
- [ ] 1.3 建立疑点清单（`long-function-findings.md`），只记录不修
- [ ] 1.4 运行 `bin/run_full_suite.py` 记录重构前基线失败集合（重点 `test_pm_verification`、`test_pm_recovery`、`test_verdict_*`、`test_transient_backoff`、`test_agent_runner_gate`、`test_turn_limit_lifecycle`、`test_impl_wip_checkpoint`）
- [ ] 1.5 **import 缝隙清点**（design D4）：固定 `_run_three_stage_verification` 内局部 import 点位（`asyncio`/`importlib`/`sys`/`VerifyEngine`/`load_scenarios`/`selfcheck_contract_light`）为「MUST 保留在运行时函数体内」基线，记录依赖 `patch("core.verify_engine.VerifyEngine")` 的测试文件清单
- [ ] 1.6 **模块级 patch 缝隙清点**（design D7）：固定 `core.agent_runner.runner` 的 `subprocess`/`time`/`json`/`datetime`/`commit_wip_checkpoint` 与 `core.pm_engine.verification.subprocess` 等的当前 patch 语义基线（`test_turn_limit_lifecycle.py`、`test_impl_wip_checkpoint.py`、`test_main_tree_deps_provision.py`、`test_verify_command_port.py`、`test_blocked_reverify_gate.py`、`test_frozen_scenario_schema_migration.py`）
- [ ] 1.7 **契约测试处置清单**（design D5/D6）：定位 `tests/test_agent_runner_modules_contract.py` 的 `test_runner_below_3800`（L170–173，工作树实测 3803 行已破）与 `tests/test_verification_modules_contract.py` 的过时 docstring 第 4 条；确认该文件的 `hasattr` / `def` 承载断言与 runner 侧 `inspect.getsource` 断言（L179–184）在 D1 修正口径下**均不挡路**，登记为阶段 4 处置项

## 2. 阶段 1：pipeline 侧线性段落提取（低风险优先）

- [ ] 2.1 提取 B0：`_check_entry_status` + `_reload_verify_engine_modules`（import 保持在函数体内，D4）
- [ ] 2.2 提取 B6：`_handle_verdict_evidence_rejection`（7 个 cause 分支，可每 cause 一方法）
- [ ] 2.3 提取 B7：`_read_verdict_failclosed`
- [ ] 2.4 提取 B9：`_apply_bug_found`（纯编排，门禁保持现成方法调用）
- [ ] 2.5 提取 B10：`_apply_verified`（纯编排；7 个计数器同写归零语义逐条保持）
- [ ] 2.6 运行 characterization tests 与 1.2 基线比对，确认 B0/B6/B7/B9/B10 提取后行为等价

## 3. 阶段 2：pipeline 侧剩余段落

- [ ] 3.1 提取 B1：`_load_frozen_or_escalate`
- [ ] 3.2 提取 B4：`_run_stage2_gates`
- [ ] 3.3 提取 B5：`_dispatch_judge_or_reuse`
- [ ] 3.4 提取 B8：`_handle_scenario_repaired`（尾递归调用保持原样）
- [ ] 3.5 提取 B3 的引擎执行段（**不含** env_error 回写段——该段含 continue，留在循环体内，D2）
- [ ] 3.6 B2（472 行 `while True` 循环体）**保持原位不拆**，仅在 `contract-inventory.md` 标注为「循环体，本变更不提取」（D2）
- [ ] 3.7 主函数收敛核对：`_run_three_stage_verification` 长度 ≤ 830 行（较原 1249 行下降 ≥ 1/3；D2 保留的 472 行循环体计入，且不得以内联逻辑充数），新提取方法均 ≤ 300 行；运行 characterization tests 比对基线

## 4. 阶段 3：runner 侧 attempt 状态对象与线性段落

- [ ] 4.1 引入 `_AttemptState`（design D3）：逐字段映射 14 个跨 attempt 标量，MUST NOT 改变读写顺序或作用域；改造 R0 初始化
- [ ] 4.2 提取 `_copyback_run_result`（**仅** R4 的结果文件 role/spec 戳拷回子段，L1963–1987 口径：无写点、无跨边界控制流；try 体其余部分与末句 `break` 留循环体内，D2）
- [ ] 4.3 提取 R9：`_exhausted_result`（循环后三型返回）
- [ ] 4.4 提取 R2：`_resolve_provider_candidate`（`chain_cursor` 经状态对象回写）
- [ ] 4.5 提取 R7：`_finalize_success`
- [ ] 4.6 提取 R8：`_finalize_failure_keep`
- [ ] 4.7 运行 characterization tests 与 1.2 基线比对，确认阶段 3 各提取行为等价

## 5. 阶段 4：runner 侧 except 段落与契约改写

- [ ] 5.1 提取 R6 的两个自洽子步：`_record_4xx_or_transient` 与 `_maybe_in_place_retry`（不含跨边界 continue/break，D2）
- [ ] 5.2 提取 R1：`_attempt_top_guards`（写回变量经 `_AttemptState`）
- [ ] 5.3 提取 R5：`_handle_artifact_gate_retry`
- [ ] 5.4 提取 R3：`_prepare_worktree`
- [ ] 5.5 R6 剩余主体（含跨边界控制流）**保持原位不拆**，在 `contract-inventory.md` 标注为「循环体，本变更不提取」
- [ ] 5.6 同步 `tests/test_verification_modules_contract.py`（D5）：仅改写模块 docstring 第 4 条过时表述（实测无断言挡路），并 SHOULD 在 `TestThreeStageWholeMove` **新增**「主函数收敛」断言（新增，MUST NOT 替换/删除既有断言）
- [ ] 5.7 修订 `tests/test_agent_runner_modules_contract.py`（D5/D6）：同步修订 `runner.py` 行数上限并登记新值；`inspect.getsource` 断言（L179–184）在 D1 R4 修正口径下若仍成立则 MUST NOT 改动，仅在实现把产物门移出主函数时才改锚到提取出的方法（等价强度，MUST NOT 删除）
- [ ] 5.8 主函数收敛核对：`_execute_agent_inner` 长度 ≤ 600 行（较原 907 行下降 ≥ 1/3；D2 保留的 419 行内层循环及其 except 收口计入，且不得以内联逻辑充数），新提取方法均 ≤ 300 行

## 6. 阶段 5：全量回归与收尾

- [ ] 6.1 运行 `bin/run_full_suite.py` 与 1.4 基线比对，确认不新增失败
- [ ] 6.2 核对全部模块级 patch 缝隙（1.6 清单）语义保持：逐项运行对应测试文件
- [ ] 6.3 汇报疑点清单最终态（`long-function-findings.md`）
- [ ] 6.4 逐项勾选本 tasks.md 全部已完成任务

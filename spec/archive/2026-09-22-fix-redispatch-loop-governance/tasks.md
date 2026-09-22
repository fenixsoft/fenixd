# Tasks: fix-redispatch-loop-governance

## Deliverables

```yaml
- path: core/run_task_track.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/engine.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/config.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/TokenBudgetPanel.tsx
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: tests/test_honest_exit_convergence.py
  kind: modify
- path: tests/test_redispatch_loop_governance.py
  kind: new
- path: tests/test_config.py
  kind: modify
- path: spec/changes/fix-redispatch-loop-governance/contract-inventory.md
  kind: new
- path: spec/changes/fix-redispatch-loop-governance/governance-findings.md
  kind: new
```

> `.fenix/config.template.yaml` 的 kind 已核定为 `modify`：`git check-ignore -v .fenix/config.template.yaml` 无命中（退出码 1，未被 gitignore 排除），不触发「gitignored modify」晋升 lint，无需 `reference` 分支。

## 1. 阶段 1：缺口口径反回退与收敛链契约

- [x] 1.1 静态清点：枚举全仓所有「推导 partial 缺口」的位置（`grep parse_tasks_md` 全部调用点 + `gap_from_result` 调用点），逐个判断是否只读结果文件、有无回退读主树 `tasks.md` 勾选，落盘 `contract-inventory.md`，**不留未归属项**
- [x] 1.2 固化收敛链：读 `_run_agent_worker` 与 `_run_fast_track_flow` 两处 `honest_exit_gap` 调用点，逐行记录「收敛成立后 `is_success`/`final_error` 如何改写、后续走哪条分支」，落盘 `contract-inventory.md`（作为契约测试的期望序列来源）
- [x] 1.3 契约测试：新增 `tests/test_redispatch_loop_governance.py::TestConvergenceContract`——断言收敛成立时 `is_success=True`、`final_error=None`、最终 `implemented` + verifier 入队；缺口非空但 ⊆ unattainable 时 MUST NOT 判定重派
- [x] 1.4 反回退守卫测试：断言「主树 tasks.md 全未勾选」时收敛仍成立（防读源回退到主树勾选的回归）
- [x] 1.5 建立疑点清单 `governance-findings.md`，只记录不修
- [x] 1.6 运行 `bin/run_full_suite.py` 记录基线失败集合

## 2. 阶段 2：两条车道对称化

- [x] 2.1 核对 full 与 fast-track 两处收敛调用：判据函数、收口语义、留痕三项逐项比对，差异登记进 `contract-inventory.md` 的「允许差异」表
- [x] 2.2 收敛后收口序列补测：断言收敛成立且交付物齐备时走完「零变更哨 → 交付物守卫 → relint → merge-back → verifier」；断言交付物缺件时仍走既有缺件处置（MUST NOT 因已收敛而放行）
- [x] 2.3 留痕对称测试：两条车道发生收敛时均写 `impl_unattainable_tasks` 人工待办告警，且日志含缺口清单
- [x] 2.4 **修 fast-track 收敛死路（design D2a）**：`_hard_check_fast_track` 要求结果文件带合法 `verification` 段（`parse_fast_track_verification`：scenarios 非空 + verdict ∈ {verified, bug-found}），而 `partial` + `unattainable` 的结果文件必然没有该段 → 收敛判定通过后仍被硬校验打回重派。按 design D2a **(a)** 实现：识别诚实退出收敛形态后跳过 verification 段要求，改写 `.spec.yaml` mode→full + 转 `implemented` + 入队 verifier（复用既有 `_rewrite_fast_track_to_full` / `_escalate_to_full_mode` 语义），裁决理由补记入 design
- [x] 2.5 **收敛点非法 `unattainable` 项 fail-closed（design D2b）**：`_honest_exit_gap` 与 `_task_completion_blocker` 当前丢弃 `parse_unattainable` 的 `_invalid`，在「只卡第一次」降级放行后存在洗白窗口；MUST 改为对非空 `_invalid` 判不收敛（按失败通道处置），补测试
- [x] 2.6 fast-track 收敛链测试：断言 2.4 修好后 fast-track 的 `partial` + 全申报形态不再被打回，且最终到达验证入口（fast-track 车道此前零收敛测试覆盖）

## 3. 阶段 3：同因重派熔断

- [x] 3.1 新增归因指纹助手（`_redispatch_cause_fingerprint`，范式对齐既有 `_merge_fingerprint`）：对失败归因文案归一化（剔除 run_id / 时间戳 / worktree 路径等易变段）后取稳定指纹
- [x] 3.2 STATE 字段：新增 `_redispatch_same_cause_streak` 与 `_redispatch_cause_fp` 两个 `_` 前缀字段。`StateMachine.serialize` 已有「`_` 前缀内部字段全量透传」分支（`core/state_machine.py:390-396`），**无需**改显式键表；MUST 补重启保持性测试（序列化→反序列化后两字段不丢）
- [x] 3.3 熔断接线：`dispatch` 失败重派分支中，`_redispatch_same_cause_streak` 达阈值时改走 `state_machine.freeze_for_human`（`status=blocked` + `frozen=True` + 人工升级告警 signal_type `redispatch_loop_detected` + error 文案含缺口/归因指纹与已重派轮数 + 内嵌「原状态 <冻结前状态>」子串），MUST NOT 再 `_enqueue`；指纹变化即重置 streak 为 1
- [x] 3.3b 作用域边界：断言新 streak 只在通用失败重派分支记账——merge 指纹熔断（`_merge_fp`/`_merge_streak`）、provider transient 排程、锁冲突退避、交付物守卫/relint 的 `_retry_count` 封顶四条通道的失败 MUST NOT 增减 `_redispatch_same_cause_streak`（防重复计数把非死循环判成死循环）
- [x] 3.4 修正既有空转：`retries >= max_r` 分支当前「清零 `_retry_count` 后照样 `_enqueue`」——改为真正终止自动重试（与 3.3 的同因熔断协同：达上限即冻结，不再重派）
- [x] 3.5 解冻清零：`state_machine.unfreeze_spec` 同步清零 3.2 的两个字段（人工处置后从零起算，与 `VERIFY_REDO_COUNT_FIELD`/`_inconclusive_attempts`/`ENV_BLOCK_ROUNDS_FIELD` 同款同一原子写），补断言；并断言冻结 error 内嵌「原状态 X」后经 `core/dashboard/data/admin_actions.py` 的解冻通道（`parse_orig_status` → `unfreeze_spec(status=orig)`）能还原为可调度状态、重新派发不再立即熔断
- [x] 3.6 配置键 `agents.max_same_cause_redispatches`：`config.py` 读取与归一化（正整数，缺省 3，范围 1–100，非法回退缺省）
- [x] 3.7 配置键读写与界面（项目约定：新配置项 MUST 带 Dashboard 界面）：`config_admin.py` 的 `_AGENTS_MANAGED_SUBKEYS`/`_SOURCE_KEYS`/`read_config`/`read_effective_config`/`_deep_merge_managed`/`write_config` 校验分支；`dashboard.ts` 的 `AgentsConfig` 接口；`TokenBudgetPanel.tsx` 输入项；`.fenix/config.template.yaml` 模板与说明
- [x] 3.8 熔断测试：同因连续达阈值 → 冻结 + 告警 + 不再派发；不同因不误熔断；解冻后计数清零

## 4. 阶段 4：重派成果继承

- [x] 4.1 定位 `keep_for_reuse` 全部触发点与 `cleanup(success=True)` 的位置关系，确认「runner 成功路径先 cleanup」这一事实
- [x] 4.2 扩展 keep 判定（design D4 已定为方案 ①）：把「`partial` 且收敛不成立」形态纳入 worktree 保留，判定点落在 `runner.py` 成功路径 `cleanup(wt_path, success=True)` **之前**（`runner.py` 成功分支先 cleanup 再返回，故判据必须前置，dispatch 层已无现场可保）。判据 MUST 复用 `core.run_task_track.gap_from_result` + `parse_unattainable`（`core/agent_runner/result_gate.py` 已引入二者），MUST NOT 重写第二套收敛推导；判定/保留抛异常时 fail-open 走既有 cleanup
- [x] 4.3 继承链测试：同因重派时下一轮经 `_take_reusable_worktree` 认领同一目录与分支（MUST NOT 新建 worktree）；断言正常成功推进路径的 `cleanup(success=True)` 语义不变；交叉断言 runner 侧判据与 `dispatch._honest_exit_gap` 对同一结果文件得出同一收敛结论
- [x] 4.4 与既有预算/豁免正交性测试：熔断时 `_impl_run_budget_used` 保持真实值、MUST NOT 走死亡 run 豁免

## 5. 阶段 5：全量回归与收尾

- [x] 5.1 运行 `bin/run_full_suite.py` 与 1.6 基线比对，确认不新增失败
- [x] 5.2 patch 缝隙专项：确认 `dispatch.py` / `runner.py` 的既有模块级 patch 语义（`time`/`subprocess`）未被破坏
- [x] 5.3 汇报疑点清单最终态（`governance-findings.md`）
- [x] 5.4 逐项勾选本 tasks.md 全部已完成任务

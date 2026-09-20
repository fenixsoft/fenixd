# 设计 — infra-failure-budget-exempt

## 既有覆盖边界（先盘点再扩展，评审补充）

以下同类场景**框架已实现**，本 SPEC 不重复建设，只做增量；实现时 MUST 复用而非另起通道：

- **provider 熔断/链耗尽/网关切换类**：`verification._verifier_error_is_infra`（core/pm_engine/verification.py:2723）已判定 infra；legacy 入口 verification.py:3179-3192 命中后保持原状态、不流转 bug-found → 既不增 `_verify_fail_rounds`、也不重派实现器。new 路径 test docstring 确认 circuit-open hold-state（engine.py:1305-1321 降级 legacy 路径同生效）。已有回归 tests/test_pm_verification.py（TestVerifierCircuitOpenHoldsState，含 new 路径）。**注意**：该门先于归因入口 return，预算退款挂钩点须同样覆盖（legacy 3179-3192 与 new 路径 circuit-open hold），否则 provider infra 轮仍耗实现预算，与目标 2 不符；或显式声明 provider 退款 out-of-scope。
- **report.json 的 env/blocked_env**：已有独立通道 `_handle_env_blocked_inconclusive` / `_escalate_env_blocked` + `_env_block_rounds`（core/state_machine.py:172-176 ENV_BLOCK_ROUNDS_FIELD；verification.py:115、3536，调用点 2042、3199），不占用 `_verify_fail_rounds`。阈值 2 轮冻结转人工（:3552-3553，admin 自动呼叫 Administrator 处置）。
- **陈旧/异 spec 归属的结果文件重放**：`_verifier_result_is_stale`（verification.py:2741）已判定并 re-dispatch（legacy 3230-3244；new 路径 2472-2483 状态判据丢弃 stale/foreign 结果）。
- **死亡 run 预算回退**：`_exempt_dead_run_budget`（core/pm_engine/budget.py:117-153）已实现「事后补偿」范式，本 SPEC 沿用。

## 失败分类（增量）

在验证结果归因处加 failure_class 判定，复用 `_verifier_error_is_infra` 扩展出 `enrich_failure_class`。**兼容性（MUST）**：`_verifier_error_is_infra` 保持原 bool 签名不变——legacy 路径 verification.py:3179 与 engine.py:2613 委托均按 bool 消费，三态分类另立新函数 `enrich_failure_class`，禁止原地改签名（否则 `if self._pm._verifier_error_is_infra(...)` 在字符串返回值下永远 truthy，legacy infra 门全线失效）：

- 归因入口（新路径 `_run_three_stage_verification` core/pm_engine/verification.py:1627、legacy 路径 `_run_legacy_verification`:3140，以及 `_do_spec_bug_found` core/pm_engine/family.py:448 附近——`_on_spec_bug_found` 本体在 engine.py:636，委托 `_do_spec_bug_found` 计入 fail_rounds）。
- prepare/serve 失败（构建命令退出如 tsc not found、端口不可达、自动启动失败）→ infra——**边界（MUST）**：新路径执行期端口不可达/应用失联现走 `_escalate_env_blocked`（verification.py:2042-2045 / 2103-2156）→ blocked + admin（`_env_block_rounds` 阈值 2 轮冻结，:3552-3553），infra 归类**只在其上补预算退款与 `_verify_infra_rounds` 记账，维持 env 通道 blocked 语义，不改为自动重排**（「env 失败绝不放行」是既有刻意设计）；归类挂钩点须在 env 判定处（env 分支早退，归因入口不可达）。benefit：infra 记账让 dashboard 可观测 env 通道 vs product 占比，预算退款不触发时由 `_env_block_rounds` 承载异常计数。
- worktree 创建失败 / 降级触发本身 → infra（**收窄**：仅当引发降级的具体失败命中 infra 清单——provider 派发失败、端口不可达等——才判 infra；engine.py:1305-1321 新路径任意异常即降级 legacy、plan 不可读亦降级（verification.py:1840-1862），其中含产品性失败，不得 blanket 豁免，否则与「product 失败仍正常消耗」验收冲突）。
- 结果文件「读错文件」（陈旧 / 异 spec 归属，复用 `_verifier_result_is_stale`）→ infra（沿用既有 re-dispatch）。
- **明确排除**：结果文件缺失 / 非法 JSON 的 unreadable 维持 fix-verdict-read-failclosed D4/D5 的 fail-closed（blocked + critical，新路径重试后二次不可读 verification.py:2484-2560 / legacy 3201-3290）。该分支既不消耗 `impl_run_budget` 也不增 `_verify_fail_rounds`，不在本 SPEC 问题域内；改成「自动重排不冻结」会反转既有刻意设计。
- **unknown 处置（保守原则）**：`enrich_failure_class` 三态中 unknown（无清单命中、无法归类）**按 product 保守处置**——不豁免预算、照常累计 `_verify_fail_rounds`。宁可少豁免，不可误豁免（误豁免会绕过预算闸门并掩盖真实失败计数）。

## 预算与闸门记账

- **计数时点约束**：实现预算是「实现 run 启动时 +1」（core/pm_engine/dispatch.py:669/676 → budget.py:87-100），失败分类在 run 结束才可知，故**不做计数时点感知**；沿用 `_exempt_dead_run_budget` 事后补偿范式——infra 判定命中时回退本次 `used`，独立写 `_infra_failure_count`。
- **对账交互（必做）**：补偿须同步纳入 `_budget_reconcile_has_exemption`（budget.py:243-267）。否则 infra 退款后 `_budget_exempt_runs` 仍为 0，`_reconcile_impl_budget`（budget.py:205-241）会以 runs 正常收工数回写 `used`，把退款冲掉、豁免失效。
- family.py：`_verify_fail_rounds` 仅 product 累加；infra 轮次只写 `_verify_infra_rounds`（纯观测，不参与冻结阈值 MAX_VERIFY_FAIL_ROUNDS=3）。

## 回拨（R3）

- **语义收紧**：策略生效后 infra 轮次根本不进入 `_verify_fail_rounds`，不存在「无谓轮次」可减；回拨只适用于**策略生效前已被误计入**的历史轮次。
- **数据来源**：`_append_fail_history`（family.py:488 / verification.py:4672）当前仅在 bug-found 记 `real-bugs`，需扩展为按轮记录 failure_class 作为回拨参考台账；**记录点必须提升到统一归因入口（enrich_failure_class 判定处）**：infra 轮不进入 bug-found 分支，仅在 family.py:488 扩展则台账永远不含 infra 轮——product/unknown/infra 全部记 failure_class（含 run_id）。**台账不是回拨的强制依赖**（与 R3「台账缺失不阻断回拨」一致）：策略生效前的历史轮次以人工核验 run 产物（.fenix/runs/ 终态 error）与 verification-report.md 为准，无台账亦可回拨；台账仅作策略生效后轮次的辅助提示与审计依据。
- **台账存续约束（关键）**：既有机制会在升级闸门冻结消费时清空台账（family.py:527 `_clear_fail_history`）、verified 终态时清空（verification.py:2717）。回拨针对的历史轮次台账大概率已被清空——**回拨不得依赖 fail_history 台账的持久性**。台账仅作「策略生效后」轮次的参考依据；对「策略生效前已误计入」的历史轮次，admin 重分类以人工核验 run 产物（.fenix/runs/ 终态 error 文本）与 verification-report.md 为准，台账缺失不阻断回拨。
- **方向**：回拨是把「实为 infra 却计入 fail_rounds」的轮次减回（product→infra 方向）。`env→product-bug` 是相反方向（补计），不得表述为回拨。

## 可观测

- STATE.md 新增 `_infra_failure_count` / `_verify_infra_rounds`，字段名常量落 core/state_machine.py（与 ENV_BLOCK_ROUNDS_FIELD 同范式，单一事实源）。
- **生命周期**：`_verify_infra_rounds` 与 `_verify_fail_rounds` 同生命周期——验证 PASS 唯一归零点（verification.py:2703-2706 同点清零），避免跨周期累计导致 dashboard 展示失真；`_infra_failure_count` 为生命周期累计观测值（同 `_budget_exempt_runs` 范式，不归零）。
- 时间线 / 概览展示 infra 与 product 分离的失败构成：core/dashboard/data.py（get_spec_timeline:3268 起）。

## 改动点

- core/pm_engine/verification.py：统一失败归因 enrich_failure_class + infra 分支接入。
- core/pm_engine/budget.py：infra 事后补偿 + 对账豁免纳入 infra 退款。
- core/pm_engine/family.py：闸门轮次按分类记账、失败历史台账。
- core/state_machine.py：新增字段常量。
- core/admin_monitor.py：admin 处置重分类入口触发回拨。
- core/dashboard/data.py：时间线 / 概览展示。
- tests/test_infra_budget_exempt.py：回归测试。

> 路径写法说明：仓库真实路径为 `core/...`（`.fenix/core` 仅为指向主树 `core/` 的符号链接，worktree 内不保证存在），任务与实现一律以 `core/...` 为准。

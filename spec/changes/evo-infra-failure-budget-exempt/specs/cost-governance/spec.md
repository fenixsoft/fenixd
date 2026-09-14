# 基础设施故障费控豁免（infra-failure-budget-exempt）

## 需求

### R1 失败分类（增量，先排除既有覆盖）
- 统一失败归因接口：enrich_failure_class(spec, cause) 返回 infra | product | unknown；复用 verification._verifier_error_is_infra（core/pm_engine/verification.py:2723）并扩展（保持其 bool 签名不变，三态另立新函数）。
- **新增** infra 清单：prepare/serve 失败（构建命令退出、端口不可达、自动启动失败）、worktree 冲突 / 降级触发本身（**收窄**：仅当引发降级的具体失败命中 infra 清单才判 infra，engine.py:1305-1321 新路径任意异常即降级 legacy、plan 不可读亦降级 verification.py:1840-1862，其中含产品性失败，不得 blanket 豁免）、结果文件「陈旧 / 异 spec 归属」重放（复用 _verifier_result_is_stale，verification.py:2741）。
- **已覆盖、不重复建设**：provider 熔断 / 链耗尽 / 切换类（_verifier_error_is_infra + legacy 入口 verification.py:3179-3192，new 路径 circuit-open hold 同生效）；report.json 的 env/blocked_env（_escalate_env_blocked 定义 verification.py:3536 + _env_block_rounds，ENV_BLOCK_ROUNDS_FIELD state_machine.py:176）。
- **明确排除**：结果文件缺失 / 非法 JSON 的 unreadable 维持既有 fail-closed（blocked + critical，新路径重试后二次不可读 verification.py:2484-2560 / legacy 3201-3290），**不**纳入 infra、不改为自动重排。

### R2 预算豁免
- 采用**事后补偿**（对齐 _exempt_dead_run_budget，budget.py:117-153）：infra 判定命中时回退本次实现预算增量，并独立记 _infra_failure_count，不进入冻结 blocked。**退款挂钩点覆盖全部 infra 判定处**：legacy provider 熔断门（:3179-3192）与 new 路径 circuit-open hold 先于归因入口 return，须同挂退款（或显式声明 provider 退款 out-of-scope）；预算计数在实现 run 启动时 +1（dispatch.py:669 / budget.py:87-100），infra 退款一次/轮、幂等。
- 补偿 MUST 纳入 _budget_reconcile_has_exemption（budget.py:243-267），保证 _reconcile_impl_budget 不以 runs 计数回写 used、冲掉退款。
- infra 失败后由 full_scan recovery 兜底重排验证（既有机制）；**prepare/serve 类例外**：维持 env 通道 blocked + admin 升级语义（`_escalate_env_blocked`，阈值 2 轮冻结转人工），infra 归类只补退款与 `_verify_infra_rounds` 记账，不改为自动重排。

### R3 闸门按分类记账与回拨
- _verify_fail_rounds 仅对 product 类失败累加；infra 轮次独立记 _verify_infra_rounds（纯观测，不参与冻结阈值）。
- 回拨仅针对**策略生效前已误计入**的历史轮次：依据扩展后的失败历史台账（按轮记 failure_class），把「实为 infra 却计入 fail_rounds」的轮次减回并解锁冻结。**台账记录点须在统一归因入口**（infra 轮不进入 bug-found 分支，仅扩展 family.py:488 会致台账永远无 infra 轮）；台账缺失不阻断回拨（人工核验 run 产物/verification-report.md 兜底）。env→product-bug 属相反方向（补计），不是回拨。

## 验收标准

以可复现单测为准（不依赖历史事故重放；add-web-ui 非本仓库 spec，无重放产物）：

- **infra 不耗预算**：构造 infra 类失败（如 prepare 构建命令退出 / 异 spec 结果文件）后，`_impl_run_budget_used` 回退、`_infra_failure_count` +1、`_verify_fail_rounds` 不变、spec 不冻结、自动重排验证。
- **对账不冲掉退款**：在 `_infra_failure_count > 0` 且 `_budget_exempt_runs == 0` 时跑 `_reconcile_impl_budget`，used 不被回写。
- **闸门不累加**：连续 infra 轮次不使 `_verify_fail_rounds` 达到 MAX_VERIFY_FAIL_ROUNDS（3）。
- **回拨**：构造历史 `_verify_fail_rounds=3` + 台账含 2 条 infra 轮，admin 回拨后 `fail_rounds=1`（低于阈值）且解冻。
- **D5 不回归**：结果文件缺失 / 非法 JSON 仍 blocked + critical，不自动重排。

## 场景

### 场景：infra 失败不消耗实现预算
- 假设 某 spec 已用实现预算 used=3/6，本轮验证因 prepare 构建命令退出（tsc not found）失败
- 当 框架在统一归因入口判定 failure_class=infra
- 则 used 回退至 3、_infra_failure_count 递增、_verify_fail_rounds 不变、spec 保持可自动重排（不冻结 blocked）

### 场景：product 失败仍正常消耗
- 假设 验证裁决为 product-bug 且证据充分
- 当 框架判定 failure_class=product
- 则 _verify_fail_rounds 正常 +1、实现预算不回退，达到阈值时按既有升级闸门冻结

# 成本治理（基础设施失败费控豁免）
<!-- knowledge: capability=cost-governance rev=1
     sources=spec/archive/2026-09-21-evo-infra-failure-budget-exempt -->

把验证失败按 infra / product 归因分流：基础设施失败不消耗实现预算、不累加冻结闸门，产品缺陷仍正常计费升级。

## 规则

- **统一失败归因接口**：`enrich_failure_class(spec, cause)` 返回 `infra | product | unknown`；复用 `_verifier_error_is_infra` 并扩展，保持其 bool 签名不变，三态另立新函数。
- **infra 清单**：prepare/serve 失败（构建命令退出、端口不可达、自动启动失败）、worktree 冲突/降级触发本身（仅当引发降级的具体失败命中 infra 清单才判 infra，不得 blanket 豁免）、结果文件「陈旧/异 spec 归属」重放。provider 熔断/链耗尽/切换类与 report 的 env/blocked_env 沿用既有覆盖，不重复建设。
- **明确排除**：结果文件缺失/非法 JSON 的 unreadable 维持既有 fail-closed（blocked + critical，重试后二次不可读即升级），不纳入 infra、不自动重排。
- **预算豁免（事后补偿）**：infra 判定命中时回退本次实现预算增量（对齐 `_exempt_dead_run_budget`），独立记 `_infra_failure_count`，不进入冻结 blocked。退款挂钩点覆盖全部 infra 判定处（含 legacy provider 熔断门与 new 路径 circuit-open hold）；预算计数在实现 run 启动时 +1，infra 退款一次/轮、幂等。补偿纳入 `_budget_reconcile_has_exemption`，对账不得以 runs 计数回写 used 冲掉退款。
- **闸门按分类记账**：`_verify_fail_rounds` 仅对 product 类失败累加；infra 轮次独立记 `_verify_infra_rounds`（纯观测，不参与冻结阈值）。
- **历史轮次回拨**：依据按轮记 `failure_class` 的失败历史台账，把「实为 infra 却计入 fail_rounds」的历史轮次减回并解锁冻结；台账记录点在统一归因入口（infra 轮不进入 bug-found 分支）；台账缺失不阻断回拨（人工核验 run 产物 / verification-report.md 兜底）。env→product-bug 属补计，不是回拨。
- **重排与例外**：infra 失败后由 full_scan recovery 兜底重排验证；prepare/serve 类例外——维持 env 通道 blocked + admin 升级语义（阈值 2 轮冻结转人工），infra 归类仅补退款与记账，不适用自动重排。

## 溯源

- 2026-09-21 2026-09-21-evo-infra-failure-budget-exempt（spec/archive/2026-09-21-evo-infra-failure-budget-exempt） — 新增 infra/product/unknown 三态失败归因、infra 预算事后补偿、闸门按分类记账与历史误计轮次回拨。

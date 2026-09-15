# 任务

## Deliverables

```yaml
- path: core/pm_engine/verification.py
  kind: modify
- path: core/pm_engine/budget.py
  kind: modify
- path: core/pm_engine/family.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: tests/test_infra_budget_exempt.py
  kind: new
```

> 路径以仓库真实路径 `core/...` 为准（`.fenix/core` 只是符号链接，worktree 内不保证存在）。

## 1. 统一失败归因接口 enrich_failure_class（infra|product|unknown）

- [x] 1.1 core/pm_engine/verification.py：在 `_verifier_error_is_infra`（:2723）基础上**新增** `enrich_failure_class`（infra|product|unknown），MUST **保持原 `_verifier_error_is_infra` bool 签名不变**（legacy 路径 verification.py:3179、engine.py:2613 委托均按 bool 消费，原地改签名为字符串枚举会导致 `if` 永远 truthy，legacy infra 门失效）；归因入口为新路径 `_run_three_stage_verification`（:1627）与 legacy `_run_legacy_verification`（:3140）的归因处。
- [x] 1.2 增量覆盖：prepare/serve 构建或端口失败、worktree 冲突/降级、陈旧/异 spec 归属结果文件（复用 `_verifier_result_is_stale`，verification.py:2741）；**排除** missing/非法 JSON 的 unreadable（维持 fix-verdict-read-failclosed D4/D5 fail-closed：新路径重试后二次不可读 blocked + critical，verification.py:2484-2560；legacy 3201-3290，**不**改为自动重排）。**prepare/serve 归类边界（MUST）**：新路径执行期端口不可达/应用失联现走 `_escalate_env_blocked`（verification.py:2042-2045、2103-2156；定义 :3536）→ blocked + admin + `_env_block_rounds`（阈值 2 轮冻结转人工，:3552-3553）——infra 归类只在其上**补预算退款与 `_verify_infra_rounds` 记账**，MUST 保持 env 通道 blocked 语义（不改为自动重排，「env 失败绝不放行」是既有刻意设计）；归类挂钩点须在 env 判定处（env 分支早退，归因入口不可达）。
- [x] 1.3 core/pm_engine/family.py：`_do_spec_bug_found`（family.py:448，`_on_spec_bug_found` 本体在 engine.py:636）仅 product 类累加 `_verify_fail_rounds`（unknown 按 product 保守处置，照常累加；infra 不进本分支）；扩展 `_append_fail_history`（family.py:488 / verification.py:4672）按轮记录 failure_class 作为回拨参考台账——**记录点必须提升到统一归因入口（enrich_failure_class 判定处）**：infra 轮不进入 bug-found 分支，若只在 family.py:488 扩展则台账永远不含 infra 轮，验收「台账含 2 条 infra 轮」与 design R3 落空；对 product/unknown/infra 全部记 failure_class（含 run_id）。台账不是回拨的强制依赖（design R3「台账缺失不阻断回拨」），只是辅助提示。**注意家庭引擎冻结时清空台账**（family.py:527），台账缺失不阻断 admin 回拨（回拨依据为人工核验 run 产物/verification-report.md，见 design R3）。

## 2. 实现预算 infra 事后补偿与独立记账

- [x] 2.1 core/pm_engine/budget.py：新增 infra 补偿（回退 used，对齐 `_exempt_dead_run_budget`:117），独立写 _infra_failure_count；把 infra 退款纳入 `_budget_reconcile_has_exemption`（:243-267），防 `_reconcile_impl_budget` 回写冲掉退款。
- [x] 2.2 core/pm_engine/verification.py：infra 判定命中处调用补偿并保持可自动重排（不写 blocked/frozen）。**退款挂钩点范围（MUST 明确）**：legacy provider 熔断门（:3179-3192）与 new 路径 circuit-open hold 均先于归因入口 return——若不在该两处挂退款，provider infra 轮仍耗实现预算，与「基础设施失败不消耗实现预算」目标不符；所有在归因入口前早退的既有 infra 判定点（provider 熔断、env 通道 prepare/serve）都必须挂退款，或显式声明 provider 退款 out-of-scope。退款一次/轮、幂等（避免同一 run 重复扣减）。

## 3. 闸门按分类记账与回拨

- [x] 3.1 core/pm_engine/family.py + core/state_machine.py：`_verify_infra_rounds` 记账（字段名常量入 state_machine.py，与 ENV_BLOCK_ROUNDS_FIELD 同范式）；确认其不参与 MAX_VERIFY_FAIL_ROUNDS 冻结判定；**生命周期与 `_verify_fail_rounds` 对齐**——验证 PASS 归零点两处同写（新路径 verification.py:2703-2706 与 legacy :3447），`_infra_failure_count` 为累计观测值不归零。
- [x] 3.2 core/admin_monitor.py：admin 处置重分类入口（新增），由 admin 声明「实为 infra 的历史轮次」后从 `_verify_fail_rounds` 减回并解冻。判定依据以人工核验 run 产物（.fenix/runs/ 终态 error 文本）与 verification-report.md 为准；**`_append_fail_history` 台账仅辅助提示**（冻结时已被 family.py:527 清空，缺失不阻断回拨）。**机制细化（MUST）**：① 核心 API——新增 state_machine/engine 侧 `reclassify_infra_rounds(spec_name, n, audit_reason)`：原子改写 `_verify_fail_rounds = max(0, 当前值 - n)` + 解冻 + 审计留痕（admin_store DISPOSITION 记录，幂等——按审计记录去重，重复回拨不二次扣减）；② admin 侧入口——复用 Administrator 处置文本模式挂钩（对齐 `_apply_family_waiver` 的 "waive"/"放行" 文本识别范式，admin_monitor.py:1189），另留 dashboard/CLI 手动入口供单测与人工触发；③ 目标状态——沿用 `_reset_env_blocked_after_disposition`（admin_monitor.py:1126）同款判定：实现分支已合并 → testing 直通重验；否则 → ready；④ 既有 `unfreeze_spec`（state_machine.py:588）**不清零 `_verify_fail_rounds`**，回拨必须自带 fail_rounds 原子改写，不能只调 unfreeze；⑤ 回拨只适用 product→infra 方向（减法），env→product-bug 属补计方向，不在此入口。

## 4. 可观测与回归测试

- [x] 4.1 core/dashboard/data.py：时间线/概览展示 infra 与 product 分离的失败构成（含 _infra_failure_count、_verify_infra_rounds）。
- [x] 4.2 tests/test_infra_budget_exempt.py：infra 不耗预算 / 闸门不累加 / 回拨 / 对账不冲掉退款 / D5 不回归 五场景单测。

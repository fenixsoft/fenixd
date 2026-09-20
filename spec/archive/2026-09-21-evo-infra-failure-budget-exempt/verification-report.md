# 验证报告：evo-infra-failure-budget-exempt

> ⚠️ 本报告由框架于 2026-09-15T03:16:49Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-15T03:16:49.260642+00:00

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 2.88M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| run-infra-budget-exempt-tests | 运行 test_infra_budget_exempt.py 全部测试通过（R1/R2/R3 基础验证） | pass | 0/3 | - |
| enrich-failure-class-triage | enrich_failure_class 三态分类准确：provider 熔断→infra、worktree 冲突→infra、普通失败→unknown、空判据→unknown | pass | 0/2 | - |
| api-specs-returns-failure-composition | /api/specs 返回的 spec 摘要包含 verify_infra_rounds / infra_failure_count / failure_composition 字段 | pass | 0/4 | - |
| infra-failure-no-consume-budget | infra 失败（provider 熔断）→ used 回退、_infra_failure_count+1、_verify_fail_rounds 不变、spec 不冻结 | pass | 0/2 | - |
| reconcile-does-not-overwrite-used | _infra_failure_count>0 且 _budget_exempt_runs==0 时跑 _reconcile_impl_budget，used 不被 runs 计数回写 | pass | 0/2 | - |
| consecutive-infra-does-not-accumulate | 连续 4 轮 infra → _verify_fail_rounds 保持 0，不触发 MAX_VERIFY_FAIL_ROUNDS 冻结 | pass | 0/2 | - |
| admin-reclassify-rolls-back | 历史 _verify_fail_rounds=3（冻结）+ 2 条 infra 轮 → admin 回拨 2 轮后 fail_rounds=1 且解冻；幂等重拨不二次扣减 | pass | 0/2 | - |
| d5-unreadable-still-blocked | 结果文件缺失（unreadable）→ 维持 D5 fail-closed（blocked + critical），不改为自动重排 | pass | 0/2 | - |
| infra-refund-idempotent-same-run | 预算退款幂等：同一 run 两次 infra 判定只退款一次（避免重复扣减） | pass | 0/2 | - |
| admin-disposition-triggers-reclassify | Administrator 处置文本声明「回拨 N 轮」→ _apply_infra_reclassification 从 _verify_fail_rounds 减回并解冻 | pass | 0/2 | - |
| env-blocked-keeps-blocked-semantics | prepare/serve env 阻塞（端口不可达）→ infra 记账，但 MUST 保持 env 通道 blocked 语义（「env 失败绝不放行」刻意设计） | pass | 0/2 | - |
| new-path-circuit-open-refunds-budget | new 验证路径：planner circuit-open hold → 同挂预算退款与 infra 记账 | pass | 0/2 | - |
| enrich-stale-result-infra | 陈旧/异 spec 归属结果文件（复用 _verifier_result_is_stale）→ infra 归类 | pass | 0/2 | - |
| api-spec-detail-timeline-with-failure-composition | /api/specs/<spec> 返回的 spec 详情包含 verify_infra_rounds / infra_failure_count 和 timeline 嵌套字段 | pass | 0/4 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景


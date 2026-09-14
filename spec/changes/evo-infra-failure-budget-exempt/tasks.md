# 任务

## Deliverables

```yaml
- path: core/pm_engine/verification.py
  kind: modify
- path: core/pm_engine/budget.py
  kind: modify
- path: core/pm_engine/family.py
  kind: modify
- path: tests/test_infra_budget_exempt.py
  kind: new
```

## 1. 统一失败归因接口 failure_class（infra|product|unknown）

- [ ] 1.1 core/pm_engine/verification.py：扩展 _verifier_error_is_infra 为统一 enrich_failure_class，覆盖 prepare/serve 失败、worktree 冲突、结果读取异常、legacy 降级、provider 熔断。

## 2. 实现预算 infra 豁免与独立记账

- [ ] 2.1 core/pm_engine/budget.py：ImplBudget 按 failure_class 计数，infra 不消耗 impl_run_budget、写 _infra_failure_count；infra 后自动重排验证不冻结。

## 3. 升级闸门按分类记账与回拨

- [ ] 3.1 core/pm_engine/family.py：_verify_fail_rounds 仅 product 累加；_verify_infra_rounds 独立记账；admin 重分类（env→product-bug）后回拨无谓轮次并解锁。

## 4. STATE 可观测字段与回归测试

- [ ] 4.1 tests/test_infra_budget_exempt.py：infra 失败不耗预算、闸门不累加、env→product-bug 回拨三场景单测；STATE.md 增量时间线输出 _infra_failure_count。

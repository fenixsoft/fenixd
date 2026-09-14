# 设计 — infra-failure-budget-exempt

## 失败分类
- 在 pm_engine 结果处理统一入口（_handle_verifier_result / _on_spec_bug_found 的归因处）加 failure_class 判定，复用 _verifier_error_is_infra 并扩展：
  - prepare/serve 失败（tsc not found、端口不可达、自动启动失败）→ infra；
  - worktree 创建失败 / 降级触发 → infra；
  - 结果文件读取异常（unreadable）→ infra（结构性异常，非产品缺陷）；
  - report.json 分类为 env/blocked_env → infra。

## 预算与闸门记账
- budget.py：ImplBudget.count(spec, failure_class)：infra 不耗预算，写 infra_failure_count 到 STATE。
- family.py：_verify_fail_rounds 累加前检查 failure_class；infra 轮次写 _verify_infra_rounds。
- admin 重分类动作（处置 run）回拨：override 解锁时按分类修正 _verify_fail_rounds。

## 可观测
- STATE.md 新增 _infra_failure_count / _verify_infra_rounds；dashboard 展示 infra 与 product 分离的失败构成。

## 改动点
- .fenix/core/pm_engine/budget.py：failure_class 感知计数。
- .fenix/core/pm_engine/family.py：闸门轮次按分类记账与回拨。
- .fenix/core/pm_engine/verification.py：统一失败归因入口。
- .fenix/core/pm_engine/spec_integrity.py：infra 记账写入 STATE。
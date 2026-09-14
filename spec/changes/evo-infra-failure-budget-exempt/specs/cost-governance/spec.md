# 基础设施故障费控豁免（infra-failure-budget-exempt）

## 需求

### R1 失败分类
- 统一失败归因接口：enrich_failure_class(spec, cause) 返回 infra | product | unknown。
- infra 清单：env 不可达/构建失败（prepare 步骤退出、端口不可达）、worktree 冲突、结果文件读取异常/读错文件、legacy 降级触发本身、provider 熔断（复用 _verifier_error_is_infra 模式）。

### R2 预算豁免
- impl_run_budget 计数时 infra 类失败不 +1（独立 infra_failure_count 记账）。
- infra 失败后自动重排验证（full_scan recovery 兜底已有），不进入冻结 blocked。

### R3 闸门回拨
- _verify_fail_rounds 仅对 product 类失败累加；infra 轮次独立记账。
- admin 重分类（如 env→product-bug）后，无谓轮次回拨（_verify_fail_rounds 减回）并解锁冻结。

## 验收标准
- 场景：add-web-ui 05:46 重放，infra 失败后不冻结预算、闸门轮次不累加。
- 单元测试：infra 失败不耗预算；env→product-bug 重分类后闸门轮次回拨。
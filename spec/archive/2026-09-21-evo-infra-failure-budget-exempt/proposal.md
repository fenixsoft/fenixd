# infra-failure-budget-exempt — 基础设施故障不消耗实现预算与升级闸门轮次

## 背景
add-web-ui 事件链中，基础设施类失败（report.json 陈旧 env 分类、planner 端口臆测、worktree 冲突、legacy 读错文件）被计入实现预算（4/4 耗尽冻结 blocked）与升级闸门（连续第 3 轮冻结），真实缺陷修复被打断约 1h 并推入人工裁决。这些失败不是实现质量失败，不应消耗实现预算，也不应计入升级闸门失败轮次。

## 目标
- 定义基础设施类失败清单：env 不可达/构建失败（tsc not found 类）、worktree 冲突、结果文件读取异常/读错文件、legacy 降级本身、provider 熔断（已有 _verifier_error_is_infra 先例）。
- 实现预算计数：基础设施类失败不消耗 impl_run_budget，自动重排验证而非冻结。
- 升级闸门计数：基础设施类失败轮次不计入 _verify_fail_rounds；归因修正后（如 env→product-bug 重分类）回拨无谓闸门轮次。

## 非目标
- 不改产品缺陷失败的正常预算消耗与冻结语义。
- 不合并到验证裁决稳定性（judge-rerun-stability）。

## 验收
- 基础设施失败单独计数（STATE 可观测），不触发预算耗尽冻结。
- 升级闸门对基础设施失败轮次不累加；重分类后闸门轮次可回拨。
# add-codefix-anomaly-redispatch-budget

## Why

2026-10-07 夜间 code-fix 链 6 个弃批侧共 24 个 run 计 52.91 美元、窗口内 24 轮回归全部以 parse_error 收场（回归运行器未产出 junit，fail_items 恒空，零失败面），定向重试在零失败面下整批重跑无证据价值（18 个重试轮 0 收敛）。add-codefix-parse-error-breaker 已把单 run 内连续异常熔断（阈值 2），但失败批的自动重派预算（FAIL_RETRY_MAX=3）对失败形态不敏感，且异常计数 anomaly_streak 为批 worker 局部变量、不跨批/跨链累计——本次 2 组条目仍被整批重派满 3 次、每组再烧 3 轮定向重试，构成本次损失的主要放大器。

## What Changes

- 失败批入档（record_failed_batch 与现场即弃收口块）记录回归终局形态 reg_form：anomaly（parse_error 或 failed 无明细）/ mapped（有真实失败面），连同 anomaly_streak 与重试收敛事实；fix-failed.json schema 增量键、向后兼容（旧记录缺键按 mapped 处理）。
- 失败批自动重派按 reg_form 分档：anomaly 形态预算降为 1（耗尽后走既有触顶「登记待人工+跳过条目」路径）；mapped 保持 FAIL_RETRY_MAX=3 不变。
- 同条目集复燃沿用既有合档语义，reg_form 以最近一次失败为准。
- 触发异常形态降档/停派时复用 write_regression_failed_alert 通道发一次性告警，不新增告警类型。

## Impact

- Affected specs: code-fix-lane（失败批自动重派预算行为变更）
- Affected code:
  - core/code_fix.py：record_failed_batch、FAIL_RETRY_MAX 旁新增异常形态预算常量、现场即弃收口块、失败批重派判定
- Tests:
  - tests/test_code_fix.py、tests/test_codefix_targeted_retry.py 扩展
  - 新增 tests/test_codefix_anomaly_redispatch_budget.py
- 风险：低——只改失败批自动重派的预算分档与入档字段，不动单 run 内定向重试轮数与既有熔断（add-codefix-parse-error-breaker）行为；回归进程被外部击杀（-9/-15）的根因另行处置，不在本 spec 范围。
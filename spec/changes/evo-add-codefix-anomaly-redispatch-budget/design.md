# Design

## 上下文

core/code_fix.py 现有机制：record_failed_batch（:623）入档失败批；FAIL_RETRY_MAX=3（:87）失败批自动重派预算；write_fix_reg_failures（:745-771）落回归失败清单（items 空→fallback_full=true）；_is_regression_anomaly（:939）定义 parse_error=零失败面（junit 缺失/不可解析）；add-codefix-parse-error-breaker 已实现单 run 内连续 2 次异常熔断（REGRESSION_ANOMALY_BREAKER_THRESHOLD=2，:936），anomaly_streak 为批 worker 局部变量（:5073-5077），不跨批/跨链累计；write_regression_failed_alert（:2316）为既有回归失败告警通道。

## 方案

1. 入档扩展：fix-failed.json 失败记录增加 reg_form（"anomaly" | "mapped"）与 reg_detail（anomaly_streak、mapped_rounds、重试收敛事实）。现场即弃收口块（:5220-5320 附近）入档时写入。读取兼容：缺键按 mapped。
2. 预算分档：FAIL_RETRY_MAX 旁新增 ANOMALY_FAIL_RETRY_MAX = 1；重派判定按 reg_form 取预算——anomaly 取 1、mapped 取 FAIL_RETRY_MAX。anomaly 且已重派 1 次的，直接走既有触顶路径（登记待人工 + 跳过条目 + release_failed_batch 人工解除通道不变）。
3. 复燃合档：同条目集再次失败沿用 record_failed_batch 既有合档语义，reg_form 与计数以最近一次失败为准（修复质量好转后自动回到 mapped 预算）。
4. 告警：anomaly 触发降档/停派时经 write_regression_failed_alert 发一次性告警（复用既有指纹去重），文案带 reg_form 与条目数；不新增告警类型。
5. 明确不动：单 run 内定向重试轮数、parse-error breaker 阈值与行为、fallback_full fail-closed 语义。

## 测试与回滚

- 新增 tests/test_codefix_anomaly_redispatch_budget.py：anomaly 预算=1 并触顶登记、mapped 预算=3、旧记录缺键兼容、复燃合档取最近形态、告警一次性。
- 扩展 tests/test_code_fix.py、tests/test_codefix_targeted_retry.py：reg_form 入档与既有定向重试行为回归。
- 回滚：预算常量与入档键集中可控，回滚即恢复预算常量；旧记录缺键按 mapped 保证无迁移负担。
- 回归进程被外部击杀（-9/-15）的根因（资源/外部击杀）不在本 spec 范围，proposal 已引用 add-codefix-parse-error-breaker 的诊断以免重复立项。
# run-failure-classification-circuitbreaker — run 失败三级分类与熔断冷却

## Why

2026-09-14 14:46-16:27：同型 infra 级失败（403 网关拒绝 + 402 余额不足 + 评审 budget exhausted）在 3 SPEC 上按 _review_attempts 机械重试 5 轮约 15 个 run 全失败，另 6 次评审预算耗尽同型空转；166 分钟无任何告警指出「评审 API 批量失败」（事件窗口 103 条告警无评审失败类），修复仅靠 16:27 人工改 config。与 add-control-plane-silent-failure-guards（arity 静态守卫/测试替身保真/复位路径编程错误升级/orphaned-state）互补：该 SPEC 未覆盖 run 失败类型分级与熔断。

## What Changes

- run 执行失败三级落点：
  1. 内容失败（含空白轮次）——维持既有重试语义；
  2. infra 失败（403/402/预算耗尽/CLI 进程级）——连续 ≥3 次熔断该链路：停止派发 + 升级告警 + 冷却（默认 30 分钟），冷却后自动恢复重试；
  3. 判别失败（产物已落盘）——直接消费（run-failure-artifact-first 承接）。
- 失败分类进入 ADMIN 信号体系：新信号类型 run_infra_failure（critical）+ 熔断状态持久化（.fenix/admin_infra_breaker.json，daemon 重启后恢复）。

## 验收

- 同型 infra 失败连续 ≥3 次 → 熔断：不再派发、1 条 critical 告警、冷却窗口内不重试、_review_attempts 不递增；窗口过后自动恢复重试。
- 内容失败维持既有重试；判别失败按产物消费。
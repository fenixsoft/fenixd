# Proposal: add-codefix-parse-error-breaker

## Why

code-fix 批回归若结局为 `parse_error`（junit 产物不存在/不可解析）或失败明细为空（`fallback_full`），说明回归**没有跑出可用结果**而非测试失败；此时定向重试机制 fail-closed 回退全量回归，只会反复烧 6-7 分钟全量再死于同一种死法。2026-10-07 实证：全天 20+ run、15 次回归全部耗在第 1 批——-9 用例自杀 14 连发（212-226s 高聚集）后又遭 -15 外部击杀（355.99s/357.23s 两次），3 轮定向重试全部同死，`resolved=0`，纯烧算力零产出。

## What Changes

- code-fix 批收尾定向重试循环新增**回归异常熔断**：同批内「parse_error 或（failed 但明细空/不可映射）」类失败**连续**达到阈值（缺省 2 次）时，提前终止重试循环，不再派发下一轮定向 run 与全量回归。
- 熔断收口沿用既有现场即弃语义（branch/tip_sha/明细引用入 fix-failed.json 档案，worktree 清理），批记 reason 新增 `regression_parse_error_breaker`（前端红色需人工分级渲染按未知 reason 兜底，零前端改动）。
- 告警走既有 `write_regression_failed_alert`（`regression_failed_twice` 历史兼容名不变），**不新增告警通道、不重复告警**：熔断收口与轮数耗尽收口共用同一告警调用点，按最终收口原因如实描述。
- 与 `targeted_retry_max` 上限机制正交：熔断触发时循环提前退出；未触发时既有轮数上限行为逐位不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `code-fix-lane`: 「回归失败的自动重试与丢弃」Requirement 新增回归异常熔断 Scenario——parse_error/无明细类失败连续达阈值即提前终止重试循环，不再等待 targeted_retry_max 轮数耗尽。

## Impact

- **代码**：`core/code_fix.py` 定向重试循环块（熔断计数、短路退出、新 reason 常量、告警调用点复用）。
- **兼容**：既有 `regression_failed_twice` 告警文案已按「首轮 + N 轮定向重试」如实描述（retry_rounds 由调用方传入），熔断提前收口时该参数如实取实际轮数即可；前端 `PHASE_LABELS`/reason 分级渲染对未知 reason 已有宁严勿松兜底，零前端改动。
- **风险**：熔断误触发会把「偶发环境抖动的回归」提前判死——阈值取 2（连续两次同类失败）且仅覆盖 parse_error/无明细类（真实测试失败不进熔断计数），误杀面可控。

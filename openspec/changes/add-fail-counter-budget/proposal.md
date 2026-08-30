# Proposal: add-fail-counter-budget

## Why

原地打回的失败计数器采用「连续失败」语义，每轮修复完成即归零：v2-config-page 24 小时内经历 3+ 次大型实现 run 与 2 轮验证失败，`_verify_fail_rounds` 始终未超过 1，3 轮升级闸门从未生效，spec 可无限振荡「修→验→修」而不触发人工裁决（复盘改进点 5）。同时 run 级重试（agents.max_retries=3）无跨 run 总量约束，单 spec 的累计消耗没有上限。

## What Changes

- `_verify_fail_rounds` 语义改为「本轮修复周期内的验证失败次数」：仅验证 PASS 时归零；修复轮完成重派时保留计数（第 N 轮失败后重派，再次失败记 N+1）
- 新增 per-spec 实现尝试总预算 `_impl_run_budget`（默认 4）：跨修复轮累计实现 run 次数（含首次与修复轮、含重试 attempt），达到预算 → 状态 blocked + human-escalation-alerts 告警（含 spec、已耗次数、最近失败摘要），需人工裁决
- 预算值从配置 `agents.impl_run_budget` 读取；缺省 4
- 新增配置键必须同步 Dashboard 界面能力（config 页「并行度/审批」页签区增加该配置项的编辑入口）

## Capabilities

### New Capabilities
- `fail-counter-budget`: 验证失败计数语义修正与实现尝试总预算闸门

### Modified Capabilities

（无——复用原地打回的升级闸门与告警通道，不新增状态）

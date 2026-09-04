# Proposal: fix-budget-counting-semantics

## Why

实现尝试预算闸门（add-fail-counter-budget）在 2026-08-30 interaction-contract 复盘中暴露两个计数缺陷：(1) 网关死亡类 run（异常早夭、零产出）与守卫误伤重派一样计入 `used`，故障密集日 4 次预算被无效消耗烧光，真正有产出的 run 反而被冻结（复盘：4/4 中 2 次网关死亡、2 次守卫误伤）；(2) 计数增量存在持久化竞态——日志实证 `used=2/4` 连续出现两次（读改写未原子，恢复扫描与派发并发时丢失增量）。

## What Changes

- **死亡 run 豁免计数**：实现 run 异常收工（进程死亡/零输出/网关链路耗尽，无成功结果且无失败结果产出）时回退本次启动时的计数增量（`used -= 1`），并在 STATE 留 `_budget_exempt_runs` 侧车计数；死亡侧车达阈值（6 次，走既有 `_get_config` 常量）发提醒级告警（防「死亡循环白嫖预算」的极端情况）
- **计数原子化**：`_impl_run_budget_used` 的读改写收敛到 state_machine 的单点原子更新（复用其文件锁），并在写入后回读校验；不匹配时重试一次并记审计
- **计数与 run 结果对账**：merge 成功/守卫放行后回读计数与实际完成 run 数一致，偏差时以实际为准修正并记日志

## Capabilities

### New Capabilities
（无——扩展既有能力）

### Modified Capabilities
- `fail-counter-budget`：预算计数的豁免语义、原子化与对账（源自 add-fail-counter-budget 变更，能力 spec 见 openspec/changes/add-fail-counter-budget/specs/）

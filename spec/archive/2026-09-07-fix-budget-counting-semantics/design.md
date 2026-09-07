# Design: fix-budget-counting-semantics

## Context

预算闸门计数点在 `_run_agent_worker` implementer 分支启动时 `+1`（2026-08-30 落地）。两个实证缺陷：(1) 网关死亡 run（无收工结果）照常计数——interaction-contract 复盘中 4/4 预算被 2 次网关死亡 + 2 次守卫误伤烧光，真实产出 run 反被冻结；(2) 增量为「读 STATE → +1 → 写回」的非原子序列，日志实证 `used=2/4` 连续出现两次（恢复扫描并发时增量丢失）。

## Goals / Non-Goals

- Goals：死亡 run 计数豁免（含侧车与阈值告警）；计数原子化 + 回读对账；不改变正常失败仍计数的既有语义
- Non-Goals：不做 token 级预算（token 预算由 add-cost-observability 另管）；不区分死亡原因分类；不给误伤重派做自动回滚（守卫误伤已由另一变更根治）

## Decisions

### D1 豁免实现为「回退」而非「延迟计数」
死亡判定处（恢复链路确认 run 无收工结果时）执行 `used = max(0, used - 1)`。选择回退而非启动时不计数：计数点保持单一（启动处），死亡判定点做补偿——避免在启动处预判生死。`_budget_exempt_runs` 侧车记录豁免次数，阈值 6（常量 `BUDGET_EXEMPT_ALERT_THRESHOLD`）触发一次性提醒告警（复用幂等标记模式）。

### D2 原子化收敛到 state_machine
`state_machine` 已有 STATE.md 文件锁（`_` 前缀字段的写回机制）。新增 `bump_impl_budget(spec, delta) -> int`：锁内读改写并回读校验，不匹配重试一次。计数点（启动 +1）与豁免点（死亡 -1）统一走该函数。delta 为 -1 时下限 0。

### D3 对账为日志级
merge 成功/守卫放行后，比较 used 与本 spec 实际正常收工 run 数（从 runs 目录侧车统计），偏差记 WARNING 日志（不自动改数——对账复杂化收益低，日志供人工发现）。

## Risks / Trade-offs

- 死亡判定依赖恢复链路的「无收工结果」结论，误判（实际死亡但被记正常失败）时豁免不生效 → 与既有死亡检测同源，风险不新增
- 阈值 6 的死亡循环仍会烧 token（豁免不设上限）→ 阈值告警兜底 + token 预算告警双通道覆盖
- 原子化增加一次文件锁往返 → 微秒级，可忽略

## Migration Plan

1. state_machine.bump_impl_budget 原子原语（一次提交）
2. 计数点/豁免点切换 + 侧车与阈值告警
无数据迁移（存量计数不回填）。

## Open Questions

（无）

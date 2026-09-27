# ADR-091：per-spec 预算覆盖解析优先级，夹紧单点共享

date: 2026-09-15
status: accepted

## Context

实现预算只有全局配置一档，per-spec 仅有已用计数；预算耗尽冻结后的人工出路是调大全局预算 + 解冻，波及全部 spec。需要 per-spec 覆盖时，闸门、读侧与 UI 若各自解析必然口径漂移。

## Decision

- per-spec 覆盖属性存 STATE entry（`impl_run_budget_override`）：人工管理属性不带下划线前缀（与 priority/start_after 同类），下划线前缀保留给框架私有字段（如已用计数）。
- 解析优先级：per-spec 覆盖 > 全局 config > 内置缺省；覆盖值可解析为 int 则同口径夹紧 1-10，None/非法/缺失回退全局链。全部闸门调用点（递增、死亡豁免、耗尽检查）统一补传 spec_name，闸门冻结文案与告警自然变为有效预算，零额外改动。
- 夹紧逻辑抽为模块级纯函数单点导出，dashboard 读侧（budget_effective 摘要字段）引用同一实现，禁双实现漂移；前端不重复实现解析，摘要三字段（used / override / effective）随既有增量路径更新，不为 UI 单开轮询。
- API 侧 null 合法（= 清除覆盖回退全局），bool 不算 int（显式排除）。

## Consequences

- 预算耗尽处置（调覆盖 → 解冻 → 恢复调度）在单弹窗内闭环，不再动全局波及他 spec。
- 存量 STATE 无需迁移：覆盖缺省 null 语义 = 跟随全局。
- 摘要与闸门同源解析，展示口径与拦截口径恒一致。

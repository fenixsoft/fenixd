## Why

验证场景自注册探针夹具时若未打 fixture=True（core/dashboard/registry.py:445 的缺省值本身就是 False），夹具 seed/对照告警（severity 可为 critical）即直通人工告警聚合横幅与跨项目聚合，污染人工甄别面。已两度出现：add-alert-self-heal-marking 的 selfheal-scratch-verify（2026-10-06 验证轮 critical 对照锚点上主面板、引发用户误排查）与 add-alerts-archive-and-overview-cache 的 arch-scratch-verify。人工已在 dashboard.yaml 逐条改 fixture: true 止血，但出题端无规则、无守卫，复发敞口仍在。

## What Changes

1. 规范固化：fixture-project-governance 领域文档补「验证场景注册夹具 MUST fixture=True」条目（依据 ADR-163：收窄仅在缺省聚合分支、点名查询零改动，打标对场景断言零影响）。
2. 出题规范：agents/planner-plan.md 补场景夹具注册规则与正反示例（反例即本次两个事故场景的写法）。
3. 机械守卫：core/verify_engine/scenario_static_check.py 表驱动新增扫描模式——场景命令中 add_project( 调用未带 fixture=True 即产出 judge 情报（只情报不拦截）。

## Out of Scope

- 不改 core/dashboard/registry.py 缺省值与聚合分支过滤逻辑（ADR-163 窄口径设计按工作，按路径翻转缺省与其 Decision「禁路径/名字推导」冲突）。
- 不改摄取抑制（alert-noise-governance 5.1）与点名查询行为。
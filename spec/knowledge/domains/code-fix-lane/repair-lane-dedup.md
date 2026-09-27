# 修复车道去重

<!-- knowledge: capability=repair-lane-dedup rev=1
     sources=spec/archive/2026-09-02-fix-repair-lane-dedup -->

防同一 fix 缺陷被 reset / spawn / 派发三路并行重复修复的互斥守卫。

## 规则

- reset 路径守卫：spec_bug_found 的 reset 路径（recovery 重发导致）在目标为 fix spec 且已存在同根非终态子 fix 时，保持该 spec 的 bug-found 状态不重置为 ready、不派发其实现器，仅在 error 字段注明「修复由子 fix <名称> 承载」；无子或子均已终态时既有 reset 行为不变。
- spawn 路径守卫：judge 判定 bug-found 后派生子 fix 前，若被验对象本身是 fix spec 且其自身状态为 ready/implementing（重实现已在飞或已排队），跳过派生子 fix，并在被验对象的 error/evidence 注明「修复由在飞重实现承载」；无在飞重实现（如 testing 验证态）时照常派生。
- 派发级同根互斥：调度器派发 fix spec 实现器前，检查同根兄弟是否存在 actionable 修复活动（兄弟 status 为 implementing，或 ready 且队列含其实现器条目，或存在活跃 impl/verify agent）；存在则保持本 spec ready 跳过本轮派发。仅 ready 且无队列条目不计为 actionable（防僵死 ready 永久阻塞）。
- 解封：子 fix 到达 done/pushed 后守卫不再生效，既有 reset/重派行为照常。
- 零行为差异回退保证：被验/待派发对象为非 fix spec、同根无任何非终态兄弟、或子 fix 均已终态时，三守卫完全不生效，既有 reset/spawn/派发行为逐字段一致。

## 溯源

- 2026-09-02 2026-09-02-fix-repair-lane-dedup — 新建本页：reset 路径抑制、spawn 路径跳过、派发级同根互斥三守卫与零行为差异回退保证。

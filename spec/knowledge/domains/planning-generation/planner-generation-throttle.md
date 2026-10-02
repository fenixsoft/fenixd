# planner 生成节流（planner-generation-throttle）

<!-- knowledge: capability=planner-generation-throttle rev=1
     sources=spec/archive/2026-09-11-add-planner-efficiency -->

验证管线阶段级并发上限：限制全框架同时出题的 planner 数量，降低多 planner 同打 LLM 网关的长尾延迟概率。

## 规则

- 配置键 `verify.planner_max_concurrent`（正整数 N）生效时，全框架同时处于「planner 出题中」的 run 数 ≤ N——这是跨 verify 管线的阶段级信号量，超出者持槽排队等待；配置为 0 或缺省时不节流，并发度仅受派发层 `agents.max_concurrent` 约束。
- 派发层全局并发语义不受影响：节流是管线内第二道门，派发并发与优先级调度规则照常生效。
- 持槽等待的 spec（verifier 已派发、planner 排队中）不被 recovery watch 判为 dispatch_stalled 或 stuck——其派发已发生、run 活跃，仅生成阶段在排队；不产生 dispatch_stalled 信号、不唤起 Administrator、状态不回退。
- 排队可观测：等待期间记录日志（含 spec 名与当前占用者数量），时间轴可检索。
- 场景冻结复用路径（跳过出题）不获取信号量——无 planner run 即无节流；planner run 被人工取消时释放信号量，不泄漏占位导致后续 spec 永久排队。
- 设置页「并发度」页签（ParallelSettingsPanel）提供「planner 生成节流」开关（关闭为缺省）+ 上限数值输入；开关旁注解须覆盖三点：①限制的是全框架同时在出题的 planner 数量；②作用=降低多 planner 同打 LLM 网关的长尾延迟概率；③代价=验证吞吐（排队 spec 等待更久）。配置键与设置页 UI 同步提供，不允许只有 YAML 没有界面。

## 溯源

- 2026-09-11 2026-09-11-add-planner-efficiency（spec/archive/2026-09-11-add-planner-efficiency） — 新增阶段级信号量与 `verify.planner_max_concurrent` 配置键、设置页开关与三点注解、排队不误判契约与取消释放信号量契约。

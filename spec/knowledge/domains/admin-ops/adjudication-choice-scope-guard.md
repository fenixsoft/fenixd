# 裁决 choice 作用域守卫与结果前置回写

<!-- knowledge: capability=adjudication-choice-scope-guard rev=1
     sources=spec/archive/2026-10-09-evo-fix-global-signal-choice-execution -->

裁决 choice 执行链（Administrator 自动处置与人工下拉共用执行器）的作用域路由防护与终态回写纪律：全局信号不执行 spec 作用域动作，处置终态以 choice 执行结果为准。

## 规则

- choice 作用域由注册表逐项显式声明（`spec_scoped` 字段，缺省按 True 保守处理），执行器与消费端据此守卫，MUST NOT 硬编码动作清单。
- 全局信号判定单源 `is_global_spec`：spec 为 None/空串，或被占位符 `'global'` 顶替（`maintenance_runs` 以 `'global'` 占位空 spec，run 名、pending 记录与处置记录的 spec 均由此而来；大小写与空白变体同判）——全局信号在执行端表现为存在 spec 名，实际无具体 spec 可操作。
- 执行器守卫（正确性底线）：全局信号对 spec_scoped 动作拒绝执行，返回明确错误且不触碰任何 spec 状态机；非作用域动作不受限。
- 未注册 signal_type 的跨信号全表反查放行仅对非 spec_scoped 动作生效；spec_scoped 动作经 `resolve_choice` 返回 `scoped-no-reverse` 拒绝，不再兜底放行。
- 双层设防：消费端（`admin_monitor._apply_choice_execution`）对全局信号的 spec_scoped choice 提前跳过（`skipped=True` 形态返回 + INFO 留痕），执行器守卫兜底正确性；两层共用注册表同一解析单源防漂移。
- 结果前置回写：choice 执行结果并入处置终态判定——执行成功才把信号回写 handled/resolved；执行失败（含守卫拒绝与非法 choice_id）信号记 `result=failed`、`action_taken` 记动作名、处置记录 error 留痕，信号保留待重审可重新处置。
- 留痕与闭环解耦：`mark_signal_handled` 的 action_taken/result 留痕参数与 handled 置位解耦（`handled=False` 只留痕不闭环）；缺省调用行为向后兼容（置 handled、不写留痕字段）；ESCALATION 记录不经该方法闭环（既有语义不变）。
- 收口不断路：全局信号（含未注册 signal_type）经非作用域等价动作（如 ack_self_heal「确认自愈·继续观察」）正常收口，不滞留 pending 无路可走；提示词呈现侧不过滤 spec_scoped 选项，守卫职责在执行时兜底。

## 溯源

- 2026-10-09 evo-fix-global-signal-choice-execution（spec/archive/2026-10-09-evo-fix-global-signal-choice-execution） — 新建本页：注册表 spec_scoped 作用域声明与 is_global_spec 判定、执行器全局守卫与全表反查收紧、消费端提前跳过双层设防、结果前置回写（失败记 failed 保留待重审）、mark_signal_handled 留痕与闭环解耦、ack_self_heal 全局收口动作

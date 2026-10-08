# 设计（fix-global-signal-choice-execution）

## 现状与根因

- 处置消费链：admin_monitor 消费 pending 处置记录（core/admin_monitor.py:5076 取 spec），调 _apply_choice_execution（core/admin_monitor.py:5060-5111）执行 choice。
- 终态回写在 choice 执行之前：core/admin_monitor.py:4345-4379 回写 resolved（门槛仅校验 result 非 pending/非 escalate/success/信号记录存在），choice 执行在其后（:4395），失败仅记 ERROR 不阻塞收尾（:5067-5071 docstring 自述）。
- 占位源头：core/agent_runner/maintenance_runs.py:245 以 'global' 占位空 spec（run 名、pending 记录、AdminDisposition.spec 均由此），使全局信号在执行端表现为存在 spec 名。
- 执行端无作用域守卫：retry_review 映射 _exec_review_unfreeze（core/dashboard/data/admin_actions.py:2271-2273），首行 parse_state 查 spec 不在即报错（:1928-1946）；signal_type 未注册时跨信号全表反查放行（:2251-2262）。
- 人工通道已有同类防护先例：core/dashboard/routes/alert_routes.py:421-433 空/无合法 choice 直接 400，:458-467 执行失败 400 且不标记 handled。

## 方案决策

1. **作用域声明进注册表**：在裁决 choice 注册表（core/dashboard/data/adjudication_choices.py）逐 choice 增加 spec_scoped 标记（retry_review 等为 True），执行器据此守卫，避免硬编码动作清单；跨信号全表反查（admin_actions.py:2251-2262）对 spec_scoped 动作不再兜底放行。
2. **双层设防**：执行器拒绝是正确性底线；消费端 _apply_choice_execution 对全局信号提前跳过 spec_scoped choice 并留 INFO（与 :5079-5082 既有『无关联 spec 跳过』分支同型），避免无谓报错。
3. **回写纠偏采用结果前置**：将 choice 执行结果并入终态回写判定——失败改记 failed、保留信号待重审、处置记录 error 留痕；成功才 resolved。落点约定：failed/action_taken 写到告警记录（SIGNAL 记录）字段；DISPOSITION 记录现无 error 字段（admin_store.py 处置落库 dict 无此键），实现时新增该键（记录为自由 dict schema，加字段无迁移成本）。与 evo-signal-preprobe-handled-writeback 引入的预探写回逻辑的先后序在实现时对齐（预探写回发生在唤起前，不与本链冲突）。
4. **留痕**：mark_signal_handled（core/admin_store.py:584-596）扩展 action_taken/result 参数，缺省值保持向后兼容（既有调用点 core/admin_monitor.py:2441/:4368、core/dashboard/routes/alert_routes.py:471、core/dashboard/data/admin_alerts.py:110 不传参行为不变）。**留痕与 handled 置位必须解耦**：mark_signal_handled 现语义是置 handled=true（幂等闭环），choice 失败留痕若复用该语义会直接违反「失败保留待重审」（目标 2）——扩展时须增加 handled 置位开关（缺省 True 兼容既有调用）或独立只留痕不闭环的方法；失败路径以不置 handled 的形态写 action_taken/result，成功路径才闭环。
5. **全局等价动作**：注册表补一个非 spec 作用域（spec_scoped=false）的『确认自愈/继续观察』类动作，保证全局信号执行收口不断路。挂载与可达性约定：全局形态信号多为未注册 signal_type（实例 ce27a93f9dca 即 daemon_errors，注册表无此桶），故该动作除声明在可能全局形态的已注册桶内外，还须依赖「非 spec_scoped 动作保留全表反查放行」（决策 1 的收紧只针对 spec_scoped 动作）对未注册信号可达；提示词呈现侧不强制过滤（执行时守卫已兜底），控制改动面。

## 风险

- 回写顺序调整涉及 admin_monitor 处置收尾主路径，需保证 spec 作用域既有流程回归通过（tests/test_adjudication_choices.py、tests/test_admin_disposition_failure_context.py）。
- admin 会话若仍选择被拒动作：守卫拒绝 + failed 回写 + 留痕已闭环，信号保留待重审后可重新处置。
- mark_signal_handled 签名扩展需兼容既有调用点（缺省参数）。
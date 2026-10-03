## Deliverables

```yaml
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: core/dashboard/data/admin_actions.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/admin_store.py
  kind: modify
- path: tests/test_adjudication_choices.py
  kind: modify
- path: tests/test_global_signal_choice_guard.py
  kind: new
```

## 1. 执行器作用域守卫

- [ ] 1.1 core/dashboard/data/adjudication_choices.py：为裁决 choice 注册表逐项声明作用域标记（retry_review 等 spec 作用域动作标 spec_scoped=true），供执行器守卫使用，取代对 signal_type 的跨信号全表反查兜底（core/dashboard/data/admin_actions.py:2251-2262 对 spec_scoped 动作不再放行）。
- [ ] 1.2 core/dashboard/data/admin_actions.py：execute_adjudication_choice（:2205 起）对 spec 为空或占位 'global' 的信号拒绝执行 spec_scoped choice，返回明确错误文案；非作用域 choice 不受影响。
- [ ] 1.3 core/dashboard/data/adjudication_choices.py：为全局信号保留至少一个非 spec 作用域（spec_scoped=false）的可执行 choice（如『确认自愈/继续观察』），避免全局信号无可选动作。可达性约定：全局形态信号多为未注册 signal_type（如 daemon_errors，注册表无此桶），该动作在已注册桶内的声明 + 1.1 保留的「非 spec_scoped 动作全表反查放行」共同保证其对未注册信号可执行；提示词呈现侧不过滤（design 决策 5）。

## 2. 消费路径路由与回写纠偏

- [ ] 2.1 core/admin_monitor.py：_apply_choice_execution（:5060-5111）对全局信号（spec 为空或 'global'）跳过 spec_scoped choice 并留 INFO 留痕，与 :5079-5082 既有『无关联 spec 跳过』分支同型。
- [ ] 2.2 core/admin_monitor.py：调整终态回写序（:4345-4395），choice 执行失败时不得回写 result=resolved 与 handled=true——信号保留待重审（不置 handled），失败落点：告警记录 result 记 failed、action_taken 记动作名（经 2.3 扩展参数、handled=False 形态写入），处置记录 error 字段留痕（DISPOSITION 记录现无该字段，新增）。
- [ ] 2.3 core/admin_store.py：mark_signal_handled（:584-596）扩展 action_taken 与 result 参数（缺省值向后兼容，既有调用点 admin_monitor.py:2441/:4368、alert_routes.py:471、admin_alerts.py:110 不传参行为不变），choice 执行成败均留痕到告警记录（当前恒为 null，见 core/admin_store.py:426）。留痕与 handled 置位解耦：增加 handled 置位开关（缺省 True）或独立只留痕方法——失败路径留痕但 MUST NOT 置 handled=true（与 2.2 一致），成功路径才闭环。

## 3. 测试

- [ ] 3.1 tests/test_adjudication_choices.py：扩展 TestApplyChoiceExecution，新增全局信号 × spec 作用域 choice 用例：应被跳过/拒绝且信号不回写 resolved。
- [ ] 3.2 tests/test_global_signal_choice_guard.py（新建）：覆盖执行器守卫（spec=null 与 'global' 两种形态拒绝 retry_review、未注册 signal_type 不再全表反查放行、非作用域 choice 正常执行）与 mark_signal_handled 留痕字段断言。
- [ ] 3.3 运行 tests/ 下 alert 与 disposition 相关既有用例（含 tests/test_admin_disposition_failure_context.py、tests/test_signal_preprobe_handled_writeback.py——其 :340 处对 mark_signal_handled 的 spy 断言直接覆盖被 2.2 调整的回写链，tests/test_admin_disposition_reschedule.py），确认人工端点 core/dashboard/routes/alert_routes.py 的既有防护（非法 choice 400 且不标记 handled）不回退。
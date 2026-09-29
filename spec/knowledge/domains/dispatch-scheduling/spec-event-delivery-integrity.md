<!-- knowledge: capability=spec-event-delivery-integrity rev=1 sources=spec/archive/2026-09-02-fix-dispatch-orphan -->

# SPEC 事件投递完整性

同状态行动性更新的事件补发、bug_found 重发的幂等无害化与状态机半写读取防御：语义上需要行动的状态写回不得因「status 未变化」而丢失派发机会。

## 现行规则

- 同状态行动性重置必须触达调度路径：pm_engine 通过 state_machine 写回一个行动性更新且 status 未发生变化时（典型：fix 子 SPEC 重置为 ready、error 更新后重新可派发），对应的 dispatch 事件（spec_ready 等）必须被触达（实现为 pm_engine 写回后直调 `_on_spec_ready`）；该更新不得因状态未变化而静默丢失派发机会。
- 补发与真实事件不双重排队：补发路径已将 SPEC 排队后，随后真实状态变化的 spec_ready 触达（如人工修改状态）不产生重复队列条目，仅一条生效。
- bug_found 重发幂等且非破坏：full_scan 对持续处于 bug-found 的父 SPEC 的每轮 re-trigger 幂等；其 spec_bug_found 处理器发现 fix 子 SPEC 已存在时——子 SPEC 处于推进态或已完成态（implementing/testing/implemented/verified/done/pushed）时不改变子 SPEC 状态并记录跳过日志；任何情况下不清空 implementer_run 与 tester_run 字段。
- fix 子 SPEC 处于 ready 且无任何派发记录（implementer_run 为空）时允许既有 reset 行为，但 implementer_run/tester_run 不被显式清空。
- 状态机半写读取防御：`state_machine.read_all()` 对解析结果做规范化——无法构成 dict 条目的行不得以字符串形态进入返回值；发现非法条目时记录 warning 日志并跳过，不影响其余条目返回，不抛异常。

## 溯源

- [2026-09-02 2026-09-02-fix-dispatch-orphan](spec/archive/2026-09-02-fix-dispatch-orphan/) — 新增同状态行动性更新的事件补发契约（同状态重置不再静默丢派发）、bug_found 重发的幂等无害化（连续扫描不降级 implemented 子 SPEC、不清空跟踪字段）与状态机半写读取防御。

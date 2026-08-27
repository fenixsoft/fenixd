# spec-event-delivery-integrity

## ADDED Requirements

### Requirement: 同状态行动性重置必须触达调度路径
当 pm_engine 通过 state_machine 写回一个行动性更新且 status 未发生变化（典型：fix 子 SPEC 重置为 ready、error 更新后重新可派发）时，系统 SHALL 保证对应的 dispatch 事件（spec_ready 等）被触达，允许的实现方式为 pm_engine 在写回后直调 `_on_spec_ready`；该更新不得因状态未变化而静默丢失派发机会。

#### Scenario: fix spec 同状态重置后获得派发
- **WHEN** 周期扫描对 bug-found 父 SPEC 重发 spec_bug_found 且其 fix 子 SPEC 已处于 ready
- **THEN** 处理完成后该子 SPEC 的实现派发动作在本次扫描周期内被触发（队列中可见或已派发）

#### Scenario: 真实事件与补发不双重排队
- **WHEN** 补发路径已将 SPEC 排队，随后 STATE.md 又发生真实状态变化的 spec_ready 触达（如人工修改状态）
- **THEN** 队列中不出现重复条目，仅一条生效

### Requirement: bug_found 重发幂等且非破坏
full_scan 对持续处于 bug-found 的父 SPEC 的每轮 re-trigger SHALL 幂等。其 spec_bug_found 处理器在发现 fix 子 SPEC 已存在时 MUST 满足：子 SPEC 处于推进态或已完成态（implementing/testing/implemented/verified/done/pushed）时，不改变子 SPEC 状态并记录跳过日志；任何情况下不得清空 implementer_run 与 tester_run 字段。

#### Scenario: implemented 子 SPEC 在连续扫描下不被降级
- **WHEN** 父 SPEC 处于 bug-found 且其 fix 子 SPEC 为 implemented，连续执行两轮 full_scan
- **THEN** 子 SPEC 两轮后仍为 implemented，implementer_run 与 tester_run 保持原值

#### Scenario: ready 但无历史工作的子 SPEC 正常重置
- **WHEN** fix 子 SPEC 首次被创建为 ready 且无任何派发记录（implementer_run 为空）
- **THEN** 允许保留现有 reset 行为，但 implementer_run/tester_run 不被显式清空

### Requirement: 状态机半写读取防御
state_machine.read_all() SHALL 对解析结果做规范化：无法构成 dict 条目的行不得以字符串形态进入返回值；发现非法条目时记录 warning 日志并跳过，不影响其余条目返回。

#### Scenario: 半写状态的读取不抛异常
- **WHEN** 构造一个含字符串形条目的 STATE.md 输入调用 read_all()
- **THEN** 返回包含全部合法 SPEC 条目，warning 被记录，无 TypeError 抛出

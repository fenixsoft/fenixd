# arbiter-lane Spec

## ADDED Requirements

### Requirement: 禁立项红线与框架缺口 todo 路由

Arbiter 的处置动作面 SHALL 以 SPEC 问题为界：解冻、重验、载荷落地、重出题等既有白名单动作不变；**MUST NOT 立项**——不再消费调查报告产出 drafted SPEC（立项写点、目录物化、节流三限一并退役）。调查中发现框架缺口（机制/车道/注册表/代码面缺陷，修复涉及框架代码或产品面变更）时，SHALL 在调查报告 `gaps` 数组上报（topic + 证据 + 影响面 + 候选方向），框架消费端逐条记入 `.fenix/todo.md`（自省队列），由框架自改进车道按既有机制统一消费立项。todo 记录 MUST 走既有 fs_utils todo 锁与 todo_format 结构契约，条目按「可直接起草 SPEC」标准并带来源标记（arbiter + 触发签名 + run_id）。台账演进：立项类写点 `spec-proposed` / `proposal-dedup` 改为 `gap-noted`（append-only 既有条目原样保留）；消费端对切换窗内旧 `proposals` 字段 MUST 容错（记 WARNING 台账，不落池、不静默丢弃）。台账留痕不变：每次记 todo 与去重跳过均在 `arbiter_ledger.jsonl` 落 `gap-noted` 记录。

#### Scenario: 框架缺口记 todo 不立项

- **WHEN** arbiter 调查报告 gaps 数组含一条框架缺口（如注册表缺口）
- **THEN** 框架消费端在 todo.md 落一条符合结构契约的条目（来源标记 arbiter+签名+run_id），不物化 spec 目录、不写 STATE 条目，台账落 gap-noted

#### Scenario: 不再产 drafted SPEC

- **WHEN** 任意 arbiter 调查完结（无论结论为何）
- **THEN** 不存在 arbiter 来源的新 drafted SPEC：无 spec/changes 目录物化、无 add_spec 调用；todo.md 是唯一的框架缺口出口

#### Scenario: 白名单动作面不受扰

- **WHEN** SPEC 问题触发 arbiter 处置（解冻/重验/载荷落地等白名单动作）
- **THEN** 行为与本需求落地前一致——红线只收走立项，不收缩处置面

#### Scenario: 切换窗旧报告容错

- **WHEN** 代码切换窗内旧 prompt 的 arbiter run 产出仍带 proposals 数组
- **THEN** 消费端记 WARNING 台账（gap-noted 附「旧字段 proposals 已退役」）后丢弃，不落池、不抛异常

#### Scenario: 自进化消费既有机制接手

- **WHEN** todo.md 中存在 arbiter 来源的框架缺口条目
- **THEN** 每日自省/自进化车道按既有 todo 消费机制评估立项，无需 arbiter 侧任何后续动作

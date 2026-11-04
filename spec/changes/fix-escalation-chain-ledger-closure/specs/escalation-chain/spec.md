# 能力规格：升级处置链——链上 admin run 终态落账与 choice 执行

（修改既有能力 escalation-chain，spec/knowledge/domains/admin-ops/escalation-chain.md）

## ADDED Requirements

### Requirement: 链上 admin run 终态即时落账（final 台账闭合）

链派发的 admin run 在 `run_administrator` 返回后、后续分支判定（handoff / 越界复核 /
成功闭环 / 失败计点）之前，MUST 立即写 final DISPOSITION 记录闭合该 run 的 pending；
落账写点 MUST 单源（admin_monitor 直接路径 `_worker` 与链路径共用同一落账助手，
字段形状一处定义）；append 失败 MUST try/except 降级 WARN 留痕且不阻断链分支判定。

字段形状对齐直接路径 final append（`core/admin_monitor.py:8214-8253`）：至少含
`kind=disposition`、`signal_type`、`spec`、`severity`、`description`（disp.problem，
空则回落信号描述）、`action_taken`（disp.actions_taken）、`result`（disp.result）、
`recommended_action`、`summary`、`admin_run_id`（disp.run_id）、`escalate`、`error`、
`failure_evidence`、`choice_id`、`suggested_choice`、`choice_payload`。

#### Scenario: 成功闭环出口落账

- **WHEN** 链派发的 admin run 处置成功（success ∧ result∈{resolved, partially-resolved} ∧ 非 escalate）
- **THEN** admin_alerts 中存在 `admin_run_id=<run_id>` 且 result 非 pending 的 final 记录，
  与链 closed 事件同轮出现；该 run 的 pending 不再被孤儿看护判为超时孤儿

#### Scenario: 超范围转单出口落账

- **WHEN** admin 产出 `handoff: "arbiter"` 转单
- **THEN** 同样存在带该 run_id 的 final 记录（result 为管理员终态原值，escalate 位保持
  disp 原值），链继续 Arbiter 相；该 run 的 pending 已闭合

#### Scenario: 落账失败降级

- **WHEN** final 落账 append 抛异常（store 不可写等）
- **THEN** 链分支判定照常继续（不因落账失败丢失 handoff/闭环判定），WARN 留痕含 run_id；
  pending 保持 pending 由孤儿看护既有语义兜底（宁多告警不静默）

#### Scenario: 落账不变式守卫

- **WHEN** 任意链派发路径执行完成（closed / handoff / exhausted）
- **THEN** 守卫测试断言：admin_alerts 中存在带该 run_id 的非 pending 处置记录
  （复刻首例事件 …6474 时间轴作为回归锚——该形态 MUST NOT 再产生无 final 的孤儿 pending）

### Requirement: 链成功路径执行注册表 choice

closed 出口在 `_close_chain_success` 之前 MUST 执行 `disp.choice_id` 指向的注册表动作，
复用与人工 alert-resolve、admin_monitor 直接路径同一执行机器（执行逻辑抽为模块级助手，
AdminMonitor 方法委托之，MUST NOT 复制分支逻辑）；链侧既有越界白名单复核保持先行——
白名单外的 choice 仍转单 Arbiter 不执行。执行结果 fail-closed 语义与直接路径同款：
执行失败/跳过时 MUST NOT 伪造闭环（不产生 chain-closed 事件、不落成功终态语义），
链事件记执行失败留痕，该件按链既有失败语义处理（计失败/转单/上升）。

#### Scenario: payload 型 choice 链上生效

- **WHEN** 链派发 admin run 产出 `choice_id=revise_scenario_reverify` 且带 choice_payload
  （在白名单内）
- **THEN** 执行器被调用并完成载荷动作（成对写回场景文件等），逐动作 DISPOSITION 记录
  落账，链闭环事件在执行成功后写

#### Scenario: choice 执行失败不伪造闭环

- **WHEN** 链上 choice 执行器报错（载荷非法/执行器异常）
- **THEN** 不写 chain-closed 事件、不按成功闭环处理；失败留痕（链事件含执行错误），
  该件进入链既有失败语义（重试/转单/上升任一）

#### Scenario: 白名单外 choice 保持转单

- **WHEN** admin 产出白名单外的 choice_id（预算/豁免类人类拍板面动作）
- **THEN** 不执行 choice，仍按既有越界复核转单 Arbiter（不计失败），final 记录照常落账

### Requirement: 链事件携带 admin run id 结构字段

链事件（chain-closed / chain-handoff 等 admin 相事件）的 `run_id` 字段 MUST 落实际
admin run id（现取 `arbiter_run_id` 对 admin 相恒空、run id 只在文案里）； Arbiter 相
事件字段语义不变。

#### Scenario: 链事件 run_id 可查

- **WHEN** 链 admin 相写出 chain-closed / chain-handoff 事件
- **THEN** 事件记录 `run_id` 等于该次 admin run 的 run_id，可供孤儿看护按 run_id 精确联查

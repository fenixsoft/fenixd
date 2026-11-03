# arbiter-lane Spec

## MODIFIED Requirements

### Requirement: 触发面与改道注册

框架 SHALL 在升级边两个咽喉层注册处置链派发：`StateMachine.freeze_for_human`（机器「冻结+告警」成对单一入口）与 `PMEngine._send_human_escalation_alert`。触发面为**黑名单制**（add-escalation-chain-admin-arbiter）：默认全部升级边信号入链（链序 Admin→Arbiter→人工），仅黑名单配置内的信号绕过全链直达人工队列；原白名单枚举（blocked/frozen/争议类 10 信号）与排除表（预算/数据完整性/队列异常 5 信号）取消——排除表语义并入黑名单配置且初始为空集。以下事件仍 MUST NOT 触发链派发：`freeze_spec`（dashboard 人工冻结）、`mark_frozen_hold`（冻结终止簿记）、`frozen_until` 定时冻结（scheduled-unfreeze 自愈在先）。同 spec 同失败签名派发受配额治理（Admin 尝试配额 2 次/签名、Arbiter 复现配额 2 次/签名，复位窗 7 天或 spec 状态迁移）取代原「只派发一次」；全局单飞——同一时刻至多一个 Arbiter run，后续触发排队串行（单飞队列深度上限不变）。dead-man/停机类签名维持永久单次。链入口按信号来源判定防自环：链成员处置输出走链内转单，不重新入链。

#### Scenario: 机器冻结自动触发

- **WHEN** 验证链场景计划争议连续 2 轮触发 `freeze_for_human`
- **THEN** 框架派发链头 Admin 处置（不直接落人工队列），并记录派发事件

#### Scenario: 人工冻结不触发

- **WHEN** 用户在 Dashboard 对某 spec 执行人工冻结（`freeze_spec`）
- **THEN** 不派发链（Admin/Arbiter 均不触发），升级边行为与改动前一致

#### Scenario: 定时冻结不触发

- **WHEN** 某 spec 带 `frozen_until` 定时解冻目标被冻结
- **THEN** 不派发链（到期由既有 scheduled-unfreeze 自愈）

#### Scenario: 同签名配额治理

- **WHEN** 同一签名链上已自主处置 2 次后问题第 3 次复现，或已有 Arbiter run 在飞时再次触发
- **THEN** 前者强制上升人工（配额耗尽）/ 后者进入单飞队列串行等待

#### Scenario: 黑名单信号绕过全链

- **WHEN** 黑名单配置含某信号类型且该信号触发
- **THEN** 不派发 Admin/Arbiter，告警直达人工队列（降级态降噪语义）

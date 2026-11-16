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

**存量回扫（承接 add-arbiter-backlog-sweep，合入次序在其后）**：触发面 SHALL 另含启用时一次性存量回扫——daemon 启动后（`arbiter.enabled=true`）与 config 热更新 disabled→enabled 跃迁时各执行一次，扫描 STATE 中 `frozen=true` 且 `admin_alerts` 存在同 spec 未处理（pending）机器升级告警的存量 spec（`frozen_until` 非空的定时冻结排除），命中者经链管线入队派发（链头 Admin，沿用既有 dedup/单飞/预算约束）。回扫 MUST 幂等：与事件触发共用同签名 dedup，二次回扫不重复派发。回扫一次性哨兵与「存量迁移」（escalation-chain）版本哨兵互不重入：回扫消费在案 pending 入链派发，迁移只收口已闭环 pending 且 MUST NOT 回填入链。

### Requirement: 自主处置白名单

首期可自主处置类白名单：①冻结场景文件拯救（无主产物鉴定：加载器校验失败+归属查证非 planner 产物→删除+显式 status 解冻）；②裁决落位/verdict 缺失考古；③验证侧计数冻结复位（impl run 预算上调不再一概禁止——由预算豁免拍板动作面承接，见「Arbiter 拍板与复现配额」）；④worktree 陈锁清扫；⑤WIP 门/在飞闸门分拣提交。实现者若评估②⑤鉴定成本过高，SHALL 可降级为「首期落地①③④，②⑤只产裁决包不处置」并在 design.md 注明。白名单外（产品缺陷终裁、无考古证据的场景集语义取舍、逻辑矛盾）MUST 只产裁决包，MUST NOT 擅动状态；预算政策类由本能力（add-escalation-chain-admin-arbiter）的预算豁免拍板动作面承接（写 spec 预算 override 字段+台账留痕），取代 add-arbiter-lane「预算政策 MUST 只产裁决包」的旧限制。同签名自主处置受配额治理（复现配额 2 次/签名、复位窗 7 天或 spec 状态迁移；dead-man/停机类维持永久单次）——取代原「同一 spec 同一失败签名只自主处置一次」纪律。

#### Scenario: 无主坏产物拯救

- **WHEN** 冻结现场的场景文件无法通过加载器校验且归属查证为非 planner 产物（如 verifier 杂交写回）
- **THEN** Arbiter 删除该文件、显式 status 解冻、触发重出题/重验，spec 恢复流转

#### Scenario: 白名单外不擅动

- **WHEN** 冻结原因是产品缺陷终裁类（verdict 为 bug-found 待人工取舍）
- **THEN** Arbiter 仅产裁决包（报告+选项+推荐），不改变 spec 状态

#### Scenario: dead-man 类配额例外

- **WHEN** dead-man/停机类签名曾被自主处置、复位窗过后同签名再次触发
- **THEN** 不再自主处置，直接上升人工（永久单次语义，配额复位不适用）

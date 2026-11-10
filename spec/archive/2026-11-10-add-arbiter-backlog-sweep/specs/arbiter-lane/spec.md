# arbiter-lane Spec

## MODIFIED Requirements

### Requirement: 触发面与改道注册

框架 SHALL 在升级边两个咽喉层注册 Arbiter 派发：`StateMachine.freeze_for_human`（机器「冻结+告警」成对单一入口）与 `PMEngine._send_human_escalation_alert`。仅 blocked/frozen/争议类 condition 进触发面。以下事件 MUST NOT 触发 Arbiter：`freeze_spec`（dashboard 人工冻结）、`mark_frozen_hold`（冻结终止簿记）、`frozen_until` 定时冻结（scheduled-unfreeze 自愈在先）、token 预算耗尽、spec_integrity 内容缺失、queue 异常类告警。同 spec 同失败签名只派发一次；全局单飞——同一时刻至多一个 Arbiter run，后续触发排队串行。

**存量回扫（add-arbiter-backlog-sweep）**：触发面 SHALL 另含启用时一次性存量回扫——daemon 启动后（`arbiter.enabled=true`）与 config 热更新 disabled→enabled 跃迁时各执行一次，扫描 STATE 中 `frozen=true` 且 `admin_alerts` 存在同 spec 未处理（pending）机器升级告警的存量 spec（`frozen_until` 非空的定时冻结排除），命中者经既有 dedup/单飞/预算管线入队派发。回扫 MUST 幂等：与事件触发共用同签名 dedup，二次回扫不重复派发。

#### Scenario: 机器冻结自动触发

- **WHEN** 验证链场景计划争议连续 2 轮触发 `freeze_for_human`
- **THEN** 框架派发 `arbiter-<spec>-<ts>` run（dsh 车道），并记录派发事件

#### Scenario: 人工冻结不触发

- **WHEN** 用户在 Dashboard 对某 spec 执行人工冻结（`freeze_spec`）
- **THEN** 不派发 Arbiter run，升级边行为与改动前一致

#### Scenario: 定时冻结不触发

- **WHEN** 某 spec 带 `frozen_until` 定时解冻目标被冻结
- **THEN** 不派发 Arbiter run（到期由既有 scheduled-unfreeze 自愈）

#### Scenario: 同签名去重与单飞

- **WHEN** 同一 spec 的同一失败签名已派发过 Arbiter，或已有 Arbiter run 在飞时再次触发
- **THEN** 不重复派发 / 新触发进入单飞队列串行等待

#### Scenario: 存量冻结回扫派发

- **WHEN** daemon 启动（或 arbiter 由 disabled 热更新为 enabled）时，存在 `frozen=true` 且有同 spec 未处理机器升级告警的存量 spec
- **THEN** 该 spec 经既有管线入队派发 Arbiter（如冻结中的 evo-refine-midflight-outlier-dims 现场形态）

#### Scenario: 回扫排除语义

- **WHEN** 存量 spec 为 `frozen_until` 非空的定时冻结，或 `frozen=true` 但无同 spec pending 机器升级告警（人工冻结形态），或 `arbiter.enabled=false`
- **THEN** 回扫不派发，行为与不启用回扫时一致

#### Scenario: 回扫幂等

- **WHEN** 回扫执行后 daemon 重启再次回扫，或回扫与事件触发先后命中同一同签名触发
- **THEN** 同签名 dedup 生效，不产生第二次派发

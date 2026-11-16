# escalation-chain Spec

## MODIFIED Requirements

### Requirement: Admin 车道链上语义

Admin SHALL 作为链第一级以既有受限形态处置（受限工具、只见当前 run 注入结果）：

- 尝试配额 2 次/签名（run 崩溃/超时计一次；自判超范围转单不计失败；派发前 spec 已 frozen 不派发不计尝试；run 终态 frozen-terminated 空壳击杀——0 API 轮次即被冻结终止——视为未尝试不计配额）
- 超范围转单为结构化产出 `handoff: arbiter` + `handoff_reason`（新增字段，MUST NOT 重载 `result=escalate` 现语义）；Administrator prompt 契约段同步
- 处置成功的终态收口 MUST 同时完成信号收口与 spec 状态恢复可运行（框架侧 side-effects，显式 status 解冻、拒绝 parse 兜底——与 Arbiter `_apply_disposition_side_effects` 同型纪律）
- 链头派发前置预检：派发 Admin run 前 SHALL 读取 spec 冻结态，frozen=True 时 MUST NOT 派发（该件转 deferred 留痕，见「链让行留痕与唤醒」；解冻后由看护扫描重派）

#### Scenario: Admin 烧满配额转 Arbiter

- **WHEN** 同一签名 Admin 处置连续 2 次 run 失败
- **THEN** 该件转单 Arbiter（附 Admin 尝试痕：run 摘要与失败原因），不再派 Admin

#### Scenario: Admin 超范围转单不计失败

- **WHEN** Admin 处置产出 `handoff: arbiter`（如预算类信号超出环境运维面）
- **THEN** 该件立即转 Arbiter，Admin 配额计数不变

#### Scenario: Admin 处置成功解冻 spec

- **WHEN** Admin 修复了导致 `verify_env_blocked` 冻结的环境问题并落 resolved 终态
- **THEN** 框架侧 side-effects 以显式 status 解冻该 spec 并触发重验证（无「告警闭环但 spec 永久 frozen」残留）

#### Scenario: 派发前 frozen 预检不烧配额

- **WHEN** 链头 Admin 派发前读取 spec 态发现 frozen=True
- **THEN** 不派发 Admin run、不计尝试配额、不记失败；该件转 deferred 留痕，解冻后由看护扫描重派

#### Scenario: 冻结击杀空壳不计尝试

- **WHEN** 链头 Admin run 派发即被 spec 冻结终止（0 API 轮次，终态 frozen-terminated）
- **THEN** 链不记 Admin 失败、配额计数不变；该件按 deferred 留痕处理（与预检同出口）

## ADDED Requirements

### Requirement: 链让行留痕与唤醒

链在办互斥守卫命中（同 spec 在飞 admin run，且该 run 非本链成员）时，链 SHALL 让行（deferred）且 MUST NOT 静默丢弃：在链状态文件 in_flight 区留 `phase: deferred` 条目（含被让行对象标识与让行时间戳），替代现行的整条清除。AdminMonitor 巡检 SHALL 扫描 deferred 条目：被让行 run 已终态且该签名信号未收口时，重新触发该件链派发（走链派发器既有单飞/互斥守卫，MUST NOT 绕过）；deferred 条目纳入既有 in_flight 超时 reap，超时无进展照常清理。防自环规则不变：看护重派是链内转单边的恢复动作，MUST NOT 作为新信号重新计签。

#### Scenario: 让行留痕

- **WHEN** 链头派发命中同 spec 在飞 admin run（manual-intervention 等非链成员通道所派）
- **THEN** in_flight 区留 `phase: deferred` 条目（含被让行对象与时间戳），链不再整条清除登记

#### Scenario: 被让行对象死亡回喂重派

- **WHEN** 被让行 admin run 已终态且该签名信号未收口（spec 仍 blocked/冻结或告警仍在挂）
- **THEN** 看护巡检重新触发该件链派发（链单飞队列与互斥守卫照常生效），链不再静默挂起等信号复发

#### Scenario: 让行条目超时清理

- **WHEN** deferred 条目超过 in_flight 超时阈值且链未恢复推进
- **THEN** 照常被 reap 清理（与链在办件同一超时机制），不产生永久滞留条目

#### Scenario: 全链痕消失后兜底升级不受扰

- **WHEN** 同签名链痕（in_flight/deferred/arbiter 在飞）全部消失且 pending disposition 仍超时
- **THEN** 孤儿看护照常升级人工（兜底语义保留，见 human-escalation-alerts）

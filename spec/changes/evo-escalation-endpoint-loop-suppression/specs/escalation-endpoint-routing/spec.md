# escalation-endpoint-routing Specification

## ADDED Requirements

### Requirement: 链终点件不回派 Arbiter 车道

携带链上下文（chain_context 非空或 entry 含 chain 字段）的链终点升级件，在升级告警落库后 MUST NOT 触发 ArbiterLane 的再提交（submit_for_alert）；升级件零后台补叙（叙事生成链已随 consolidate-alerts-to-ops-page 1.2 退役，告警以机械文案落盘），其消费归属为人工裁决面。

#### Scenario: Arbiter 升级包落告警后不再入队

- **WHEN** Arbiter 产出的裁决包升级告警（chain.endpoint_kind=arbiter-escalated）完成 store.append
- **THEN** 不发生 source=escalation-alert 的同签名 arbiter 入队，升级件停留人工裁决面

#### Scenario: 链队列满回落件不受影响

- **WHEN** 链队列满导致回落为兜底直派件（chain_context=None、entry 无 chain 字段）
- **THEN** 该件按既有直派逻辑正常处理，守卫不误伤

### Requirement: 车道入口对链上下文提交短路

ArbiterLane.submit_for_alert 入口 MUST 对携带链上下文的 entry 短路（记录一条跳过日志后返回），作为咽喉守卫之外的第二道防线。

#### Scenario: 绕过咽喉的新调用点被入口拦截

- **WHEN** 未来新增调用点直接以含 chain 字段的 entry 调用 submit_for_alert
- **THEN** 入口识别链上下文并短路，不产生 arbiter run

### Requirement: 配额不再是自环的唯一停止机制

升级告警回派 Arbiter 的行为被守卫阻断后，arbiter_rulings 配额仅约束真实的多次升级裁决，MUST NOT 再被自环回派消耗。

#### Scenario: 同签名第二次升级仍可获裁决

- **WHEN** 同签名出现新的真实升级件（新证据、非回派）
- **THEN** 在 arbiter_rulings 配额内正常获得 Arbiter 裁决，行为与现状一致
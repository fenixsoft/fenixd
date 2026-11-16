## ADDED Requirements

### Requirement: warning_stale_triage 的裁决选项集

裁决注册表 MUST 为 `signal_type=warning_stale_triage` 登记裁决桶，且桶内 MUST 含 `ack_triage`（`spec_scoped=true`，仅留痕收口、不触碰任何 spec 状态机）与 `revise_scenario_reverify`（按模块级单源常量 `_REVISE_SCENARIO_REVERIFY` 引用，`requires_payload=true` 字段逐字不变）。注册后 `choices_for("warning_stale_triage")` MUST 非空、由 `_send_human_escalation_alert` 写出的告警 MUST 携带 choices、`choices_for_admin_chain` 结果 MUST 含上述两项。

#### Scenario: 注册后告警携带选项
- **WHEN** 验证管线发出 signal_type=warning_stale_triage 的 critical 升级告警
- **THEN** 落盘记录含 choices 字段，元素为 ack_triage 与 revise_scenario_reverify 的注册表快照

#### Scenario: 链上 Admin 处置不再空白名单
- **WHEN** 升级链 Admin 对该信号产出 choice_id=ack_triage
- **THEN** `_admin_choice_allowlist` 返回非空集合并含 ack_triage，越界复核放行，执行器按 ack_self_heal 动作分支留痕收口

#### Scenario: 场景门失效可走修订通道
- **WHEN** resolve_choice("revise_scenario_reverify", "warning_stale_triage")
- **THEN** 桶内精确命中，返回 requires_payload=true 的选项与空拒绝原因；缺载荷时既有载荷硬门按原样拒绝

#### Scenario: 人工 alert-resolve 有合法选项
- **WHEN** 前端对该信号告警打开裁决下拉并提交 ack_triage
- **THEN** 后端按注册表校验通过并执行，不再因空 choice 集返回 400

#### Scenario: 未注册信号的越界归因可区分
- **WHEN** 链上 Admin 对某个仍未注册裁决桶的 signal_type 产出任意 choice_id
- **THEN** handoff 原因为「信号未注册裁决桶: <id>」，不再误写「人类拍板面专属」；拒绝语义与放行面不变

#### Scenario: 跨桶一致性在 import 期钉死
- **WHEN** 新桶内选项的 action/spec_scoped/destructive/requires_payload/risk_tier 与其它桶同名 id 漂移
- **THEN** 模块 import 即抛 AssertionError（_assert_registry_consistency）

## Deliverables

```yaml
- path: core/dashboard/data/adjudication_choices.py
  kind: modify
- path: core/pm_engine/escalation_chain.py
  kind: modify
- path: tests/test_adjudication_choices.py
  kind: modify
- path: tests/test_warning_stale_triage_bucket.py
  kind: new
```

## 1. 注册表与归因

- [x] 1.1 core/dashboard/data/adjudication_choices.py：新增模块常量 `_ACK_TRIAGE`（id=ack_triage、label/desc 说明「triage 结论留痕并收口信号、不触状态机」、action=ack_self_heal、spec_scoped=true、risk_tier=reversible-experiment），并在 `_ADJUDICATION_REGISTRY` 注册 `warning_stale_triage: (_ACK_TRIAGE, _REVISE_SCENARIO_REVERIFY)`（后者按引用复用，不复制字段）。
- [x] 1.2 core/pm_engine/escalation_chain.py：`_admin_choice_allowlist` 区分「signal_type 未注册」与「已注册但选项被全部过滤」两种空集，越界转单文案对前者输出「信号未注册裁决桶: <choice_id>」、对后者保持「人类拍板面专属」；拒绝与放行语义不变，白名单读取失败的 fail-open 行为不变。
- [x] 1.3 tests/test_adjudication_choices.py：把注册表覆盖断言从 13 桶改为 14 桶，并在逐信号选项集断言中加入 `warning_stale_triage: {"ack_triage", "revise_scenario_reverify"}`。

## 2. 测试

- [x] 2.1 tests/test_warning_stale_triage_bucket.py：断言 `choices_for("warning_stale_triage")` 含 ack_triage 与 revise_scenario_reverify，且 revise_scenario_reverify 的 requires_payload=true；断言 `choices_for_admin_chain("warning_stale_triage")` 两项均在（不被人类专属排除集过滤）。
- [x] 2.2 tests/test_warning_stale_triage_bucket.py：经 `FamilyGovernor._send_human_escalation_alert` 发出该信号，断言落盘告警含 choices 字段；断言 `resolve_choice("revise_scenario_reverify", "warning_stale_triage")` 桶内命中，而同一 choice 对未注册信号仍返回 scoped-no-reverse（守卫不回退）。
- [x] 2.3 tests/test_warning_stale_triage_bucket.py：断言未注册信号的链上越界归因文案为「信号未注册裁决桶」，已注册信号的越界文案仍为「人类拍板面专属」。
- [x] 2.4 回归：tests/test_escalation_chain.py 的越界转单用例与 tests/test_global_signal_choice_guard.py 全绿（拒绝语义未被打松）。

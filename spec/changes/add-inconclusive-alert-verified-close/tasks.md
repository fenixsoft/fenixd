## Deliverables

```yaml
- path: core/alert_lifecycle.py
  kind: modify
- path: tests/test_alert_lifecycle.py
  kind: modify
```

## 1. 条件族扩展（core/alert_lifecycle.py）

- [ ] 1.1 新增 `CONDITION_SPEC_VERIFIED = "spec_verified"` 常量与翻绿状态集常量（`("verified", "done", "pushed")`）；`_SIGNAL_CONDITIONS` 登记 `"inconclusive_loop": CONDITION_SPEC_VERIFIED`（废除排除注释，改写为收口语义定调：「收口=问题前提消失、证据=验证翻绿、非替代人工裁决」）；`_recognized` 收录新条件
- [ ] 1.2 `evaluate_alert` 新增 `spec_verified` 条件判定分支：status ∈ 翻绿状态集 → 生成翻绿注记（spec 名 + 「验证已翻绿」+ updated 时刻，缺失不硬造）；status ∈ 其余在途态/缺失/spec 不在状态表 → None；分支位于既有 `CONDITION_SPEC_DELIVERED_ADJUDICATED` 分支同层，`blocked` 拦截与既有终态路径零改动
- [ ] 1.3 `BACKFILL_SIGNAL_TYPES` 收录 `"inconclusive_loop"`，并确保回填路径（无 trigger）按 `spec_verified` 条件推断（与在册映射同条件，MUST NOT 落入 `_resolve_note_for_condition` 的 terminal_or_unblocked 宽松分支）
- [ ] 1.4 注释同步改写（防语义漂移验收项）：`SELF_HEAL_SIGNAL_TYPES` 定义处、「刻意不在注册表，永不自愈闭环」注释（文件头与 `_self_heal_channel_applies` 附近共三处）——改写为「自愈面维持排除（安静≠翻绿证据）；spec 附着面挂 spec_verified 条件」

## 2. 测试（tests/test_alert_lifecycle.py）

- [ ] 2.1 翻绿收口场景：escalation 与 kind=signal 双形态 × `verified`/`done`/`pushed` 三态 → 可闭环、注记断言（含 spec 名、翻绿表述、updated 时刻；updated 缺失用例不硬造）；其余字段逐位保留断言
- [ ] 2.2 不收口回归场景：`testing`/`implemented`/`blocked`/状态缺失/spec 不在状态表 → evaluate_alert 返回 None（附 16:19 auto 重派反例注释锚）；人工 `handled=True` 用例逐位不变断言
- [ ] 2.3 存量回填场景：无 trigger 的 `inconclusive_loop` escalation（spec=pushed）回填判定可闭环且注记带「存量回填」前缀；回填条件断言为翻绿状态集（testing 用例不收口）；既有 `verify_fail_escalation` 回填行为零回归断言
- [ ] 2.4 自愈面维持排除断言：`inconclusive_loop` 不在 `SELF_HEAL_SIGNAL_TYPES`、安静场景不自愈收口（既有用例如有需同步口径，无则补最小用例）

## 3. 自检

- [ ] 3.1 全量跑 `python3 -m pytest tests/test_alert_lifecycle.py -x -q` 通过；并跑 admin_monitor 相关既有测试（`tests/` 下告警扫描消费面，grep find_resolvable 调用方）确认周期扫描链路零回归

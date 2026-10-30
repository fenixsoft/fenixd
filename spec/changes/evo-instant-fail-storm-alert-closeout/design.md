# 设计：instant-fail-storm-alert-closeout

## 落点

1. core/alert_lifecycle.py：_SIGNAL_CONDITIONS（:112-125）加 instant_fail_storm 条目挂 CONDITION_SPEC_DELIVERED_ADJUDICATED（:63）；:394-412 注记泛化；backfill 路径（:66 BACKFILL_SIGNAL_TYPES 或扩展映射）覆盖存量无 trigger 条目的一次性收口。
2. core/agent_runner/runner.py：_alert_instant_fail_storm（:8394-8413）写入点调 attach_trigger（:144-154）；_record_instant_fail（:8320-8376）死亡路径留存启动 stderr 尾部与 worktree 状态快照（落告警 entry 证据字段或既有 evidence 目录）。
3. core/self_review.py：未处理 escalation 明细（:2200-2236）加龄期计算与超 24 小时标注提醒，兼容 admin_monitor 节流闸。
4. 测试：tests/test_alert_lifecycle.py——instant_fail_storm 告警在 spec pushed/done 后自动 resolved（留痕不删）；冷却中（非终态）不提前收口（负例：防止误挂 unblocked 条件的回归锚）；无 trigger 存量条目按所选路径收口且不误伤在途条目。

## 风险与权衡

- 终态口径必须 terminal-only（pushed/done/archived）：「verified」非状态值；挂 unblocked 条件会在冷却期被非 blocked 判定提前闭环，恰使「秒挂风暴升级」失去存在意义。
- 龄期提醒与 admin_monitor 提醒节流叠加可能互相吞并，实现需同日幂等。
- 秒挂取证快照有界（stderr 尾部＋状态文件），不落大对象。
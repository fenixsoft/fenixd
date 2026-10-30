# 设计：instant-fail-storm-alert-closeout

## 落点

1. core/alert_lifecycle.py：_SIGNAL_CONDITIONS（:112-125）加 instant_fail_storm 条目挂 CONDITION_SPEC_DELIVERED_ADJUDICATED（:63）；:393-411 终态收口注记按 signal_type 中性泛化（现 :404-407 硬编码 spec_delivered_no_content 文案）。存量收口不走 backfill 注册表（:66 BACKFILL_SIGNAL_TYPES）——该路径对无 trigger 条目复用 spec_terminal_or_unblocked 的「非 blocked 即解除」判定（evaluate_alert :412-414），会在冷却期提前闭环、违背 terminal-only；改为一次性为悬置条目补写 terminal-only trigger 后走既有自动盘点，或人工 handled（留痕）。评审实测：87f72c680499 已于 2026-10-28T02:12:34Z 人工 handled，当前台账无 instant_fail_storm 悬置条目，收口路径保留为存量盘点守护。
2. core/agent_runner/runner.py：_alert_instant_fail_storm（:8438-8478，评审时实测行号）写入点调 attach_trigger（:144-154）；_record_instant_fail（:8354-8436）死亡路径留存启动 stderr 尾部与 worktree 状态快照（落告警 entry 证据字段或既有 evidence 目录）。
3. core/self_review.py：未处理 escalation 龄期盘点（:2205 _collect_admin_summary；未处理明细现于 :2239 由创建窗口过滤产出）加龄期计算与超 24 小时标注提醒，兼容 admin_monitor 节流闸。龄期盘点的对象集必须是全量未 handled 台账，MUST NOT 复用创建窗口过滤集——调度侧窗口为 [last_run_at, now] 增量（:672），窗口内明细按构造不可能含超 24 小时条目。
4. 测试：tests/test_alert_lifecycle.py——instant_fail_storm 告警在 spec pushed/done 后自动 resolved（留痕不删）；冷却中（非终态）不提前收口（负例：防止误挂 unblocked 条件的回归锚）；无 trigger 存量条目按所选路径收口且不误伤在途条目。

## 风险与权衡

- 终态口径必须 terminal-only（pushed/done/archived）：「verified」非状态值；挂 unblocked 条件会在冷却期被非 blocked 判定提前闭环，恰使「秒挂风暴升级」失去存在意义。
- 龄期提醒与 admin_monitor 提醒节流叠加可能互相吞并，实现需同日幂等。
- 秒挂取证快照有界（stderr 尾部＋状态文件），不落大对象。
- 龄期标注若挂在窗口过滤明细上会使目标 2 永不触发（每日调度窗口 [last_run_at, now] 内条目按构造 <24 小时；评审实测 core/self_review.py:672、:2227-2239），故龄期盘点必须取全量未 handled 台账。同理 instant_fail_storm 禁入 BACKFILL_SIGNAL_TYPES（其「非 blocked 即解除」语义与 terminal-only 互斥）。
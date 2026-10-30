# 提案：instant-fail-storm-alert-closeout

## 问题

秒挂风暴升级告警在对应 spec 交付后悬置：87f72c680499（instant_fail_storm，spec=fix-scheduled-reverify-survive-restart）14:44:49Z 创建，spec 15:26:29Z 到达 pushed，此后 ≥10.5 小时 handled=false，成为当日自评摘要唯一未处理 escalation，稀释告警面并虚增未处理计数（.fenix/admin_alerts.json:2730、fenixd.log:4901-4904）。

根因（复核收窄，比「无自动收口路径」更便宜）：自动收口机制（add-alert-auto-resolve＋2026-10-27-evo-add-signal-subject-terminal-close）已建成并在运行，但 instant_fail_storm 未登记进 _SIGNAL_CONDITIONS 条件注册表（core/alert_lifecycle.py:112-125），写入点也未调 attach_trigger（core/agent_runner/runner.py:8394-8413 裸 append）——evaluate_alert（core/alert_lifecycle.py:380-388）对该告警结构性返回 None。这是「主体终态告警悬置因条件未登记」家族的第二例（前例 blocked_stuck 由 10-27 归档 spec 修复）；instant_fail_storm escalation 全史 3 条中 2 条靠人工收口、本条无人收。

伴生缺口：秒挂死亡（0 秒存活三连）无启动 stderr 与 worktree 快照，根因完全不可取证。

## 目标

1. instant_fail_storm 登记进条件注册表（terminal-only：pushed/done/archived 才收口），写入点调 attach_trigger 埋点，使新告警可走自动收口；存量悬置告警按所选路径收口一次。
2. 每日自省未处理 escalation 明细加龄期，超 24 小时未处理标注提醒。
3. 秒挂死亡路径留存启动 stderr 尾部与 worktree 状态快照。

## 非目标

- 不挂 spec_terminal_or_unblocked 条件（对非 blocked 即判解除，会在 300 秒冷却中提前闭环、使冷却告警失效——已核实 :413-415 语义）。
- 不动 cooldown 门控本体与 evo-add-instant-fail-cooldown-full-lane-gate（在途）语义。
- 不处理另一条未处理 escalation a58c46957e35（add-merged-branch-gc，spec 在途，属合理待处理）。
- 不改 add-alert-auto-resolve 与 self-heal 两个既有注册表的既有条目语义。
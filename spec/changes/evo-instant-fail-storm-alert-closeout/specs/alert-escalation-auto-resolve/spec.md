# 能力：alert-escalation-auto-resolve

## R1 条件登记与埋点

1. _SIGNAL_CONDITIONS（core/alert_lifecycle.py:112-125）登记 instant_fail_storm→CONDITION_SPEC_DELIVERED_ADJUDICATED（terminal-only：仅 pushed/done/archived 触发 resolved）；:394-412 的收口注记按 signal_type 中性泛化（不写死单类型文案）。
2. 写入点（core/agent_runner/runner.py:8438-8478 _alert_instant_fail_storm）对告警 entry 调 attach_trigger（:144-154）埋点，使新告警携带 trigger 可被自动收口盘点消费。

## R2 存量悬置收口

对无 trigger 字段的存量 instant_fail_storm 条目提供一次性收口路径：盘点全部未 handled 的 instant_fail_storm 台账条目（评审实测 87f72c680499 已于 2026-10-28T02:12:34Z 人工 handled，当前台账无悬置条目），若存在按「一次性补写 terminal-only trigger 走既有自动盘点」或「人工 handled」收口（实现中留痕）；MUST NOT 经由 BACKFILL_SIGNAL_TYPES（core/alert_lifecycle.py:66）收口——该路径对无 trigger 条目按「非 blocked 即解除」判定（evaluate_alert :412-414），与 terminal-only 口径冲突；收口后不得误伤在途合理待处理的 escalation（如 a58c46957e35）。

## R3 龄期盘点与取证快照

1. 每日自省对全部未 handled 的 escalation 台账条目（MUST NOT 仅取 core/self_review.py:2227-2239 的创建窗口过滤集——调度窗口为 [last_run_at, now] 增量（:672），窗口内明细按构造不可能含超 24 小时条目）计算登记龄期，超 24 小时未处理标注提醒（注意与 admin_monitor 节流闸兼容、同日幂等）。
2. _record_instant_fail（core/agent_runner/runner.py:8354-8436）秒挂死亡路径留存子进程启动 stderr 尾部与 worktree 状态快照，使 0 秒死亡可取证。
# 能力：alert-escalation-auto-resolve

## R1 条件登记与埋点

1. _SIGNAL_CONDITIONS（core/alert_lifecycle.py:112-125）登记 instant_fail_storm→CONDITION_SPEC_DELIVERED_ADJUDICATED（terminal-only：仅 pushed/done/archived 触发 resolved）；:394-412 的收口注记按 signal_type 中性泛化（不写死单类型文案）。
2. 写入点（core/agent_runner/runner.py:8394-8413 _alert_instant_fail_storm）对告警 entry 调 attach_trigger（:144-154）埋点，使新告警携带 trigger 可被自动收口盘点消费。

## R2 存量悬置收口

对 87f72c680499 这类无 trigger 字段的存量条目提供一次性收口路径（backfill 映射或人工 handled 二选一，实现中留痕），收口后不得误伤在途合理待处理的 escalation（如 a58c46957e35）。

## R3 龄期盘点与取证快照

1. 每日自省未处理 escalation 明细（core/self_review.py:2200-2236）计算登记龄期，超 24 小时未处理标注提醒（注意与 admin_monitor 节流闸兼容）。
2. _record_instant_fail（core/agent_runner/runner.py:8320-8376）秒挂死亡路径留存子进程启动 stderr 尾部与 worktree 状态快照，使 0 秒死亡可取证。
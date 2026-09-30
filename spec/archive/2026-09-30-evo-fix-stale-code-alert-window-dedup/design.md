# Design: stale_code 告警跨重启窗口去重

## 现状与关键事实

- fenixd.py:969-993 _update_stale_code_state：每 30 秒检测周期重算 _code_stale，仅假→真边沿继续（:991-992）；:1002-1031 写入块 append kind=ESCALATION、signal_type=stale_code、severity=warning 后立即 mark_handled（:1032-1033）。
- 查询件现成：AdminStore.latest_signal(spec, signal_type, within_minutes)（core/admin_store.py:462-475）——spec=None 匹配 daemon 级信号、kind 过滤含 ESCALATION；escalation 记录无 last_seen，窗口锚点等价按 created 判窗（admin_store.py:489-495 docstring）。
- 同构先例：admin_monitor._throttled（admin_monitor.py:2180-2185）、spec_integrity.py:229 幂等预检、DAEMON_ERROR_RESTART_COOLDOWN_MINUTES 模块常量风格（admin_monitor.py:112-123）。
- 既有测试：tests/test_stale_code_selfheal.py:104-112 断言「陈旧命中后应写 stale_code escalation 告警」（空 store 首报不受影响）。

## 设计

1. 写入块前置判定：latest_signal(None, "stale_code", STALE_ALERT_DEDUP_MINUTES) 命中即记 INFO 日志并跳过 append/mark_handled；常量 60 分钟、模块级定义，不入 config（治理参数后续可由告警治理 SPEC 统一参数化）。
2. 边沿触发、写入即 mark_handled 语义不变；超窗后新边沿照常成条。
3. 去重状态零新增：admin_alerts.json 本身即持久化判定源；存储 150 条裁剪下窗口判定只依赖最近记录，60 分钟窗远在覆盖范围内。

## 风险与边界

- 最坏情形是 60 分钟内的真·新陈旧周期被静默——窗口内实测自愈重启约 1-2 小时一次、告警紧跟主树 merge（间隔 15-30 秒），60 分钟窗与重启节奏同量级，漏报代价可忽略。
- 不折叠历史：91 条存量自然随 150 条滚动裁剪退出；如需立即释放容量属一次性运维清理，不在本 SPEC。

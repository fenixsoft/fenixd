## 落点

- fenixd.py _check_supervisor_drain_consistency（:3698，daemon 启动序列 :613 调用）：warnings 追加循环（for w in warnings → self.pm_engine._append_project_log，约 :3826-3831）前插入窗口去重判定。
- 常量：fenixd.py 模块常量区新增 SUPERVISOR_LOG_DEDUP_MINUTES = 60（与 :157 STALE_ALERT_DEDUP_MINUTES 同层）。

## 机制

1. 判定：self.admin_store.latest_signal(None, "supervisor_runtime_drift", SUPERVISOR_LOG_DEDUP_MINUTES) 非 None 即窗口命中 → self.logger.info 记「supervisor 漂移告警窗口去重命中，跳过 PROJECT_LOG 追加」并跳过追加。latest_signal 复用 core/admin_store.py:485 既有冷却查询，状态持久化于 admin_alerts.json、天然跨 daemon 重启存活（与 fenixd.py:1160-1176 stale_code 去重同构，该处代码注释已背书此状态承载方式）。
2. 首次成条：窗口未命中 → 照常 _append_project_log，随后向 admin_store 写入一条 kind=escalation、signal_type=supervisor_runtime_drift、severity=warning 的去重标记记录并立即 mark_handled（warning 不在 HUMAN_SEVERITIES，不进人工横幅；对齐 stale_code 记录写入即自动处置的语义）。
3. 降级：self.admin_store 为 None 或 latest_signal/写入抛异常时捕获，照常追加 PROJECT_LOG（保持现状），并记一次 logger.warning 说明去重状态不可用。

## 备选与取舍

- 直接扫描 PROJECT_LOG 尾部按文案+时间戳判定：无新增存储写入，但文本匹配脆弱（文案含运行时数值、时间格式耦合），且 PROJECT_LOG 无锁并发追加不安全，放弃。
- 把去重做进 pm_engine._append_project_log（core/pm_engine/engine.py:3041）：影响所有调用方、语义过宽，放弃——窗口去重是 supervisor 检查的业务语义，不是日志通道的通用语义。

## 风险

- supervisor 长期异常但窗口反复命中时 PROJECT_LOG 长期只此一条：可接受——窗口 60 分钟远短于漂移阈值 24 小时，真·新异常周期会超窗成条。
- 去重标记记录占用 admin_alerts.json 记录额度：warning 级记录同受 MAX_RECORDS=150（admin_store.py:34）环形裁剪管理，量级与 stale_code 相当，无额外风险。
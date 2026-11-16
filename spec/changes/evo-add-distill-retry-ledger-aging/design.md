# 设计：蒸馏重试台账欠账龄期升级与节流

## 现状代码

- core/knowledge.py:1444 check_retry_ledger_age：告警发射单点；:1388 RETRY_STALE_AFTER=24h 阈值；:1496 固定 severity=warning；:1396 进程内当日幂等标记（重启即失效——已观测 26 次发射中 17 次为重启驱动）。
- core/admin_store.py 已有可复用原语：latest_signal 持久窗口节流（:1415，按 max(created, last_seen) 判窗、跨重启有效）、append_if_absent（:887）、has_unhandled_fingerprint（:1576）、ESCALATION kind 常量（:43）。
- 维护检查点挂载：fenixd.py:1762 起每 300 秒周期调用。

## 设计要点

1. 龄期计算：取台账条目登记时刻到当前时刻的差，格式化进 description/evidence，连同归档 spec 名。
2. 升级判定：age 超过 72 小时且存在未处置同指纹信号时 severity 提为 major（或走 admin_store.py:43 既有 ESCALATION 通道，实现时按现有消费语义择一）。
3. 节流改造：把 :1396 的进程内 set 换成经 AdminStore 的持久判窗（latest_signal 窗口），窗口常量建议 6 小时（与既有 30~90 分钟发射节奏相比大幅降噪，又不会把 24h 首警拖过头）。
4. 升级穿透：节流判窗前先比较上次发射级别与当前应发级别，级别提升时不节流、立即发射。
5. 每日自省数据摘要无需改动：major 信号已被数据摘要信号段收集，升级后自然进入固定视野。

## 风险与回退

- 节流窗口过长会延迟欠账提醒：窗口为具名常量并注释权衡，后续可配。
- 台账条目处置后信号自然消失，无需新增核销逻辑（与条件消失自动复位的现状一致）。

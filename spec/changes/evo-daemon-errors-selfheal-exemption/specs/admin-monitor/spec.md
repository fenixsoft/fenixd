# admin-monitor Specification

## ADDED Requirements

### Requirement: 已知自愈签名不升级 daemon_errors critical

daemon_errors 升级判据 SHALL 维护单源「自愈签名注册表」，条目含签名匹配条件与对应自愈消费者说明；命中条目的 ERROR 序列 SHALL 跳过 critical 升级与重启 daemon 建议文案，但不删除日志行、不影响既有豁免（重启冷却窗/孪生指纹合并/跨日同刻判别）。

#### Scenario: WIP 重叠拦截重试不产生 critical

- **WHEN** merge-back 被 WIP 重叠 precheck 以 policy=escalate 拦截并在重试窗口内重复落 ERROR（间隔 25-120 秒）
- **THEN** 不产生 daemon_errors critical 告警，ERROR 首条仍在日志，周期消费者正常自动合回

### Requirement: 重试窗口内重复拦截聚合落行

worktree_manager merge-back precheck 的重复拦截 SHALL 在同一重试窗口内聚合：保留首条 ERROR（首阻取证），后续重试以聚合 INFO 级留痕（含重试序号），不重复计数升级。

#### Scenario: 同次合回三次拦截一次 ERROR

- **WHEN** 同一 merge-back 重试序列拦截 3 次
- **THEN** ERROR 行仅 1 条（首阻），后续为聚合 INFO 留痕，daemon_errors 复现计数不再累计

### Requirement: 豁免可审计

命中豁免签名的 ERROR SHALL 留可审计计数，审计面可区分「已豁免的自愈链路留痕」与「未豁免的真实错误」。

#### Scenario: 豁免计数可查

- **WHEN** 豁免签名命中发生
- **THEN** 审计面可见该签名命中次数，且原文 ERROR 在日志可检索
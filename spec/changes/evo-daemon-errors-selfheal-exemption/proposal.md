# Proposal: daemon-errors-selfheal-exemption

## Why

daemon_errors 升级判据是纯形态级（同指纹+10 分钟窗内复现 2 次，core/admin_monitor.py:169-171 常量、:5366 升级判定），不区分「daemon 自身故障」与「框架自愈链路的设计内过渡态留痕」，导致自愈链路的重复 ERROR 被升级成建议重启 daemon 的 critical。家族实发 ≥5 例：WIP 重叠 precheck 的 escalate 拦截（Merge-back blocked by WIP overlap precheck policy=escalate）4 天 4 条 critical（37bd6ee4 11-08、4326a321 11-08、fea09770 11-10、5406fd44 11-11；本例窗口内实际 4 条 ERROR、间隔 25/120/120.9 秒，告警定格复现 2 次）；promotion lint 族 10-31 两条 ERROR（12:33:47/12:34:51）实际召唤一次 Administrator run（12:34:57 Distress detected 日志）。而两族 ERROR 均有自带自愈消费者：WIP 拦截由 wip-defer-merge-retry 治理链周期消费者自动 merge-only 合回（core/pm_engine/dispatch/queue.py:4269 等待复查、:4009 重试，本例 04:18:12Z 闭环记录 c836b596ba9e 实证 6 分 19 秒自愈）；promotion lint 由 promotion 恢复节拍重试。critical 文案模板「建议检查根因并重启 daemon」（admin_monitor.py:5847/:5889）对这两族系统性误导。

## What Changes

- 自愈签名豁免注册表（单源）：在 _detect_daemon_errors 升级 append 前增加签名匹配跳过分支（与既有冷却窗/孪生合并/跨日判别同层），注册表条目注明各自愈消费者：①component=worktree_manager 且 message 前缀 Merge-back blocked by WIP overlap precheck (policy=escalate) → wip 周期消费者；②component=pm_engine 且 Promotion lint failed → promotion 恢复节拍。注册表形态仿 core/alert_lifecycle.py:98 SELF_HEAL_SIGNAL_TYPES 既有注册表。
- 源头聚合：worktree_manager merge-back precheck 在同一重试窗口内的重复拦截降级为聚合日志——首条 ERROR 保留作首阻取证面（首阻记账 _merge_retry_first_at 由拦截现场 wip_gate_blocked 返回值链路承载——rollback.py:857-873 依 MergeConflictInfo 写 STATE，不依赖日志行；「Merge-back blocked」文案全仓唯一消费者即 logger.error 本身，mergeback.py:752-777），后续重试不重复落 ERROR 行，从源头消除复现计数。
- 豁免可审计：命中豁免签名的 ERROR 仍在 daemon 日志可见（豁免只压制升级告警，不删日志），命中计数留痕供审计面区分「已豁免的自愈留痕」与「未豁免真错误」。

## Impact

- Affected specs: admin-monitor（新能力页）
- Affected code:
  - core/admin_monitor.py（豁免注册表+跳过分支+命中计数）
  - core/worktree_manager/mergeback.py（重试窗口内聚合日志）
  - tests/test_daemon_errors_selfheal_exemption.py（新增单测）
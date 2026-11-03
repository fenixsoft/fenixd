# 人工升级告警

<!-- knowledge: capability=human-escalation-alerts rev=4
     sources=spec/archive/2026-09-02-add-administrator-agent,spec/archive/2026-09-02-fix-graceful-shutdown-agents,spec/changes/add-escalation-chain-admin-arbiter,spec/knowledge/_inbox/done/escalation-chain-orphan-watchdog-double-path.md -->

处置链终点的例外出口：链上两级自动化（[escalation-chain](escalation-chain.md)）都无法收敛时把事件升级给人类——结构化告警持久化、Dashboard 醒目通知、孤儿检测升级口径。

## 规则

- 告警写入时机：处置链终点（Arbiter 自判失败/复现配额耗尽）、黑名单信号、降级态（`arbiter.enabled=false` 或链失能）判定须人工出场时写入升级告警，以及孤儿看护 pending 超时（链外豁免通道）；自愈不可达不让事件静默丢失，链内任一级处置成功即终态化、零人工感知。
- 机器发起的升级信号默认走处置链：处理中件不产生用户可感知告警（不推送、不进 pending、不落 admin_alerts 条目），可见性由链状态文件与 SPEC 时间轴/处置链视图承载。
- 告警记录字段：`id`、`created`、`severity`、`spec`、`description`、`evidence`、`action_taken`、`recommended_action`，并附全链痕迹（Admin 尝试痕、Arbiter 台账五段关联、链 run_id 族关联键）与剩余 choices；人工处置后可全链回溯。
- 持久化到 `.fenix/admin_alerts.json`（gitignore），daemon 重启后仍可读取。
- 记录数上限：admin_alerts.json 任何写回时自动裁剪，只保留最近 150 条；消费方（冷却去重、自动闭环）只依赖近期记录，裁剪最旧历史不影响语义。
- Dashboard 通知：存在未处理升级告警时，顶部显示醒目通知横幅（未处理告警数、最高 severity、最新告警摘要），并提供告警列表与「标记已处理」操作；标记后横幅消失，记录保留可追溯。
- 人工冻结与定时冻结不进链：`freeze_spec`（dashboard 人工冻结）与 `frozen_until` 定时冻结的告警直接等待人工处置，与链无关。
- 黑名单信号与降级态直达人工队列，按既有降噪分级生效（critical/major 进 pending、warning/minor 写入即 handled）+ narrative 补叙。
- 合成兜底类告警静默化：框架自身合成的兜底提示不进入人工升级通道。
- 孤儿检测升级口径：admin 处置 pending 超时（孤儿）时，仅当对应 run 文件（`.fenix/runs/<admin_run_id>.jsonl`）不含 interrupted 标记才升级人工告警；含 `{"type": "interrupted"}` 判定为已知中断（daemon 关闭所致）——追加 status=interrupted 终结记录终结该 pending disposition 且不产生告警，后续巡检因已终结不再处理。
- 兜底语义保守：pending 超时且 run 文件不存在或已被清理（无证据可查）时，按「无 interrupted 标记」处理——升级人工并追加终结记录防止循环告警，宁多告警不漏告警。
- 孤儿看护是链外直写出口：pending 超时升级由 AdminMonitor 以 `store.append(kind=ESCALATION)` 直写人工队列，不经 Arbiter——链契约按发射通道治理，孤儿看护为链外豁免发射通道（设计内豁免：链无法处置自己的死讯）；其链盲重复出件缺口见 [escalation-chain](escalation-chain.md)。
- 归因模板不可信：孤儿告警 description 模板固定写「疑似 daemon 重启/崩溃连带杀死 admin」，与真实死因无关（死因可为 spec 冻结击杀、优雅重启等任意形态）；排查以 run 终态证据与链状态文件为准，勿按告警叙事方向取证。

## 溯源

- 2026-09-02 史前复原 — 迁移期已存在的基线：自愈不可达时升级人工告警；合成兜底类告警静默化，不进入人工升级通道
- 2026-09-02 add-administrator-agent（spec/archive/2026-09-02-add-administrator-agent） — 固化升级告警 8 字段结构与 admin_alerts.json 持久化、150 条写回裁剪、Dashboard 横幅与「标记已处理」闭环
- 2026-09-02 fix-graceful-shutdown-agents（spec/archive/2026-09-02-fix-graceful-shutdown-agents） — 孤儿检测升级口径收窄：run 文件含 interrupted 标记的已知中断终结而不告警，无证据场景保守维持升级
- 2026-11-03 add-escalation-chain-admin-arbiter（spec/changes/add-escalation-chain-admin-arbiter/） — 升级告警改为链终点例外出口：机器升级信号默认入链零落盘（不推送/不进 pending/不落条目），仅链终点失败、黑名单、降级态落告警；上升件附全链痕迹（Admin 尝试痕/台账五段/链 run_id 关联键）与剩余 choices
- 2026-11-03 escalation-chain-orphan-watchdog-double-path（spec/knowledge/_inbox/done/escalation-chain-orphan-watchdog-double-path.md） — 折叠孤儿看护链外豁免通道定性（设计内 vs 链盲重复出件缺口）与告警归因模板不可信排查纪律（先查 run 终态与链状态文件）

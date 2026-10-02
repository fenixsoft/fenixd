<!-- knowledge: capability=human-escalation-alerts rev=2 sources=spec/archive/2026-09-02-add-administrator-agent,spec/archive/2026-09-02-fix-graceful-shutdown-agents -->

# 人工升级告警

自主处置不可达时把事件升级给人类：结构化告警持久化、Dashboard 醒目通知、孤儿检测升级口径。

## 现行规则

- 升级触发：Administrator 判断困境无法自主处置（需要人类决策、连续处置失败、涉及不可逆操作需确认）时写入升级告警；自愈不可达即升级人工，不让事件静默丢失。
- 合成兜底类告警静默化：框架自身合成的兜底提示不进入人工升级通道。
- 告警记录字段：`id`、`created`、`severity`、`spec`、`description`、`evidence`、`action_taken`、`recommended_action`，持久化到 `.fenix/admin_alerts.json`（gitignore），daemon 重启后仍可读取。
- 记录数上限：admin_alerts.json 任何写回时自动裁剪，只保留最近 150 条；消费方（冷却去重、自动闭环）只依赖近期记录，裁剪最旧历史不影响语义。
- Dashboard 通知：存在未处理升级告警时，顶部显示醒目通知横幅（未处理告警数、最高 severity、最新告警摘要），并提供告警列表与「标记已处理」操作；标记后横幅消失，记录保留可追溯。
- 孤儿检测升级口径：admin 处置 pending 超时（孤儿）时，仅当对应 run 文件（`.fenix/runs/<admin_run_id>.jsonl`）不含 interrupted 标记才升级人工告警；含 `{"type": "interrupted"}` 判定为已知中断（daemon 关闭所致）——追加 status=interrupted 终结记录终结该 pending disposition 且不产生告警，后续巡检因已终结不再处理。
- 兜底语义保守：pending 超时且 run 文件不存在或已被清理（无证据可查）时，按「无 interrupted 标记」处理——升级人工并追加终结记录防止循环告警，宁多告警不漏告警。

## 溯源

- 2026-09-02 史前复原 — 迁移期已存在的基线：自愈不可达时升级人工告警；合成兜底类告警静默化，不进入人工升级通道
- 2026-09-02 add-administrator-agent（spec/archive/2026-09-02-add-administrator-agent） — 固化升级告警 8 字段结构与 admin_alerts.json 持久化、150 条写回裁剪、Dashboard 横幅与「标记已处理」闭环
- 2026-09-02 fix-graceful-shutdown-agents（spec/archive/2026-09-02-fix-graceful-shutdown-agents） — 孤儿检测升级口径收窄：run 文件含 interrupted 标记的已知中断终结而不告警，无证据场景保守维持升级

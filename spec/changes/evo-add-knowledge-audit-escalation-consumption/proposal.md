# proposal — add-knowledge-audit-escalation-consumption

## Why

知识审计的升级通道（escalated：复核 2 轮无确定性判定后转人工仲裁，core/knowledge_audit.py:1009-1014）唯一消费者是人工，框架侧无聚合、无龄期可见性、无仲裁入口。实测积压：findings.json 13 条中 10 条 escalated 全部 verdicts=[]、page_hashes={}，first_seen 均为 2026-09-30，挂 3 天零消费。

更硬的后果是语义车道饱和锁死：每日语义转写预算 MAX_SEMANTIC_RUNS=10（core/knowledge_audit.py:63），escalated-skip 分支（:882-888）虽跳过转写仍占槽——10 条 escalated 恰好占满全部槽位，3 条 suspected 冻结在 review_rounds=1，10-03 实扫 20 条候选仅转写 0、7 条新矛盾不入台账（台账 mtime 10-02 vs 审计 state mtime 10-03 印证零写入）。evo-add-knowledge-audit-finding-ledger 的 Non-Goals 明确排除台账条目清理与容量治理，本缺口无归属地可搭车。

## What Changes

- 车道解冻：escalated-skip 不再计入语义转写预算，新候选恢复每日入账。
- 聚合与龄期：每日体检报告把 escalated 明细折叠为单条汇总（N 条 + 最长龄期）；todo 侧升级登记收敛为单条聚合行（同前缀替换，不逐条堆积）。
- 超龄注记：escalated 超过阈值天数时，在涉事知识页面顶部写「已知分歧待仲裁」机器可读注记（HTML 注释，遵守 marker 三红线，写入自提交），仲裁消费后摘除。
- 仲裁清单：.fenix/knowledge_audit_arbitration.json 作为人工仲裁唯一入口（fingerprint/decision/decided_at/note），框架在审计循环消费——命中即 _record_verdict 并删条目，复用「条目缺席即恢复自动复核」的既有重建逻辑。

## Non-Goals

- 不改审计判定能力与复核轮次封顶语义（escalate_after_rounds=2 保持）。
- 不自动裁决矛盾（人工仲裁定位不变，框架只做通路）。
- 不动台账机制本身（evo-add-knowledge-audit-finding-ledger 已建，status pushed 待归档）。
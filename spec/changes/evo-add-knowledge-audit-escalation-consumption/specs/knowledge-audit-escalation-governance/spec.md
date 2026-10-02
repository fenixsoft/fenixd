# knowledge-audit-escalation-governance

## Requirements

### R1 语义车道解冻

- escalated 条目的 skip 处理 MUST NOT 占用 MAX_SEMANTIC_RUNS 语义转写预算（跳过不计槽或单列独立预算），保证新候选每日可入台账。

### R2 聚合与龄期

- 每日体检报告（knowledge_audit_report.md）MUST 把 escalated 明细折叠为单条汇总：条数 + 最长龄期（自 first_seen 起算）。
- todo.md 的升级登记 MUST 收敛为单条聚合行（N 条待仲裁 + 最长龄期），行内容变化时 MUST 以同前缀替换而非追加（避免聚合行自身变成每日重述）。
- 聚合行 MUST 指向仲裁清单文件路径作为唯一人工入口。

### R3 超龄注记

- escalated 条目龄期超过 ESCALATED_STALE_DAYS（常量，缺省 7 天，配置键 knowledge.escalated_stale_days 可覆盖）时，框架 MUST 在其涉事知识页面顶部追加机器可读注记（HTML 注释形态，如 <!-- disputed: since=... fps=... -->）。
- 注记 MUST 遵守 marker 三红线：不得含 knowledge: 前缀（防劫持 marker 解析）、不得引用不存在的 spec/archive 路径（防 audit 悬空清理删行）、守知识页 150 行硬顶（写前检查）。
- 注记写入 MUST 走既有 [fenix] knowledge 提交路径自提交（避免成为下一轮 audit 的 dirty carryover 告警源）；对应条目被仲裁消费后 MUST 同步摘除注记。

### R4 仲裁清单消费

- 框架 MUST 读 .fenix/knowledge_audit_arbitration.json（条目：fingerprint、decision（fixed|no-conflict|false-positive）、decided_at、note），在审计循环中命中 escalated 指纹即落 verdict（复用 _record_verdict 状态迁移）并删除台账条目。
- 删除后台账条目缺席 MUST 自然恢复该页对的自动复核（既有 _new_finding_entry 重建语义，不新增机制）。
- 非法 decision / 未知指纹 MUST 跳过并留痕，不抛错不阻断审计。

## Scenarios

1. **解冻**：10 条 escalated 在册时，新矛盾候选当日仍被转写派发（不再因 skip 占槽而冻结）。
2. **聚合**：报告与 todo 各只有一条汇总行；龄期推进时 todo 行被替换而非追加。
3. **超龄注记**：escalated 挂超 7 天 → 涉事页面顶部出现 disputed 注记并自提交；人工按清单仲裁后条目删除、注记同轮摘除。
4. **仲裁闭环**：人工在清单写入某指纹 decision=no-conflict → 下一轮审计消费、台账删条目、该页对恢复自动复核。
5. **脏输入防御**：清单含未知指纹或非法 decision → 跳过留痕，审计循环不受影响。
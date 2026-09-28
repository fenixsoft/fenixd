# design — add-knowledge-audit-finding-ledger

## 台账选型与 schema

- 落盘 .fenix/knowledge_audit_findings.json，dict 以指纹为键；读写函数 _load_findings_ledger/_save_findings_ledger 对齐既有 _read_state/_write_state 的原子写模式（core/knowledge_audit.py:76-89 附近）。先例：同 SPEC knowledge-backfill 能力的 .fenix/knowledge_backfill.jsonl。
- 条目 schema：{ kind, pages: [rel_a, rel_b], rules: [rule_a, rule_b], page_hashes: {a: sha256, b: sha256}, verdicts: [{date, verdict, commit}], status, first_seen, updated_at }；status ∈ suspected / exempt / fixed / superseded-in-batch / escalated。

## 指纹与豁免键

- 指纹 = sha256(kind + 两页 rel + _normalize_rule(规则行) + digits)，全部输入在 core/knowledge_audit.py:368-369/:382 已有现成计算。
- 豁免判定另存两页全文 sha256（page_hashes）而非仅规则行指纹：疑点 8 证明同规则行在不同内容语境下判决会翻转，只有内容未变才豁免，内容一变即解冻重派，不引入漏报。

## 状态机

suspected →（no-conflict 且记录 page_hashes）exempt；（重写提交落账）fixed；任一页哈希变化 → 回 suspected；第二轮仍疑似 → escalated（终态，人工消费后清除）。待人工疑点进入挂起态等消费，不自动重派。

## 复核循环接入

- run_audit 的转写循环（core/knowledge_audit.py:640-698 附近）spawn 前查台账：命中 exempt 且两页哈希未变 → 跳过派发，体检计数加 exempt 档。
- 每个判定产出后立即回写台账（现状判定只进 details["no_conflict"] 与每日被覆盖的报告）。
- 同批去重：疑点清单在扫描开始一次性快照（:602-604 附近），同批前面的 run 提交后涉及同页的后续疑点属快照滞后重复，标记 superseded-in-batch 跳过。
- escalated 落地挂点复用 append_todo_line（core/knowledge_backfill.py:128，audit 车道已在用），零新机制。

## 同模块捆绑修复

- ADR 断链：:311 附近的 (adr_dir / "ADR-063.md").is_file() 精确名检查改为按 ADR-\d{3} 前缀 glob slug 文件，消除 ADR-015/019/034 三条永久误报（待人工队列由此获得真实消费对象）。
- state 合并：每日检查点 :122 一次性读 state，run_audit :761-762 写 last_scale 后，:141-142/:155-156 用陈旧副本回写覆盖；改为回写前重读合并。此修复同时救活存量 Requirement 的规模趋势「需精简」标记（+10% 阈值）。

## 配置

get_knowledge_lane_config（core/config.py:1866-1881）新增两键：no_conflict_exempt（默认 true，豁免开关）、escalate_after_rounds（默认 2，升级阈值）；.fenix/config.template.yaml knowledge 节（:372 附近）登记并注释。

## 风险与对策

- 复核翻转价值受损？豁免以内容哈希未变为前提，内容变更必然重派，翻转情形（疑点 8）仍可被抓出。
- escalated 终态掩盖新矛盾？ escalated 只停自动复核，todo 登记有人工可见面，消费后清除即恢复。
- 台账膨胀？每指纹一条、体量小，清理列入非目标。
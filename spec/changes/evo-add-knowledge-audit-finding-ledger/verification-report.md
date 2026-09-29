# 验证报告：evo-add-knowledge-audit-finding-ledger

> ⚠️ 本报告由框架于 2026-09-28T19:58:59Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-28T19:58:59.383086+00:00

## 结论：✅ 通过（verified）

**状态：verified — 12/12 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 12/12 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 12 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.14M |
| 本链增量 Token（输出） | 0.10M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| ka-ledger-roundtrip-atomic-fingerprint | 疑点台账持久化·读写原子性与指纹稳定性：台账 roundtrip/原子写与指纹跨文本噪声稳定（spec「疑点台账持久化」；tests/test_knowledge_audit.py:621 test_findings_ledger_roundtrip_and_atomicity、:646 test_finding_fingerprint_stable_across_text_noise；core/knowledge_audit.py:112-143） | pass | 0/4 | - |
| ka-ledger-verdict-writeback-schema | 疑点台账持久化·判定回写（直驱真实模块）：no-conflict 判定入账置 exempt 并记两页哈希、fixed 判定入账记提交、五态 schema 与 verdicts/first_seen/updated_at 齐备、save→load roundtrip（spec「判定回写」；core/knowledge_audit.py:146-191 _new_finding_entry/_record_verdict、:954-976 真实调用点 verdict 词符 no-conflict/fixed） | pass | 0/13 | - |
| ka-exempt-skip-redispatch | no-conflict 按内容豁免·内容未变不复发：次日初筛同指纹不派复核 run、体检计数出现 exempt、台账记录豁免发生时间（spec「内容未变不复发」；tests/test_knowledge_audit.py:670 test_audit_no_conflict_exempt_skips_redispatch；core/knowledge_audit.py:846-857） | pass | 0/3 | - |
| ka-exempt-unfreeze-content-change | no-conflict 按内容豁免·内容变更解冻：任一页内容哈希偏离台账记录即回 suspected 并照常派发复核（spec「内容变更解冻」；tests/test_knowledge_audit.py:699 test_audit_content_change_unfreezes_exempt；core/knowledge_audit.py:858-870） | pass | 0/3 | - |
| ka-page-hash-exemption-key-failopen | 豁免键与异常路径（直驱真实模块）：豁免键为两页全文 sha256（改文即变、还原即复、缺页=空串哈希）；台账缺失/损坏 fail-open 空台账不炸初筛（spec design.md「指纹与豁免键」；core/knowledge_audit.py:147-156 _page_hash、:112-120 _load_findings_ledger） | pass | 0/7 | - |
| ka-superseded-in-batch-dedup | 待人工挂起·同批快照滞后去重：首笔转写纠偏后涉同页的后续疑点标 superseded-in-batch 跳过（spec「待人工挂起与第二轮升级」；tests/test_knowledge_audit.py:293 test_audit_semantic_rewrite_commits、:329 断言 counts.superseded≥1；core/knowledge_audit.py:820-832） | pass | 0/3 | - |
| ka-escalate-second-round-todo | 待人工挂起·第二轮升级：同指纹第二轮仍疑似即置 escalated 终态、todo.md 出现升级登记、停止自动复核（spec「第二轮升级人工」；tests/test_knowledge_audit.py:728 test_audit_second_suspected_round_escalates；core/knowledge_audit.py:916-931） | pass | 0/3 | - |
| ka-config-ledger-keys-defaults | 配置键·缺省与容错（直驱+单测）：no_conflict_exempt 缺省 true/显式 false 生效/非 bool 回退 true，escalate_after_rounds 缺省 2/显式 3 生效/0 与 bool 等非法值回退 2（tasks 4.1；core/config.py:1938-1966 get_knowledge_lane_config；tests/test_knowledge_audit.py:836 test_knowledge_lane_config_ledger_keys） | pass | 0/11 | - |
| ka-config-template-keys-registered | 配置模板登记：.fenix/config.template.yaml knowledge 节登记 no_conflict_exempt: true 与 escalate_after_rounds: 2 并附注释（tasks 4.2；.fenix/config.template.yaml:380/:384 实测行） | pass | 0/3 | - |
| ka-adr-slug-prefix-match | ADR 断链前缀匹配：按 ADR-\d{3} 前缀匹配盘上 slug 形态文件名，ADR-015 引用命中 ADR-015-<slug>.md 不再判断链（直驱 _adr_file_exists + e2e；spec「slug 形态引用不再误报」；core/knowledge_audit.py:396-401、:418 调用点实参为裸编号形态；tests/test_knowledge_audit.py:770 test_adr_broken_chain_matches_slug_filenames） | pass | 0/7 | - |
| ka-state-merge-keeps-last-scale | 状态检查点合并回写：体检写入 last_scale 后检查点回写 state 不再被陈旧副本覆盖、次日报告出现「上次 X 行」规模趋势后缀（spec「last_scale 不再丢失」；tests/test_knowledge_audit.py:793 test_checkpoint_merge_keeps_last_scale_and_report_trend；core/knowledge_audit.py:122-160） | pass | 0/3 | - |
| ka-full-suite-regression | 知识审计车道全量回归：tests/test_knowledge_audit.py 全部 24 例通过（含本 SPEC 台账/豁免/升级/ADR/state 合并 9 例新增与既有车道用例；实测本地 24 passed in 0.99s，断言文案取自真实输出末行「24 passed」） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景


# design — add-knowledge-audit-escalation-governance

## D1 解冻点

escalated-skip 分支（core/knowledge_audit.py:882-888）现状：counts[pending_manual] += 1 + 报告留痕 + continue，但发生在语义循环内、已占 semantic_all[:10] 切片名额（:801）。改法：组装 semantic_all 时排除 status=escalated 的指纹（或 skip 分支补归还槽位计数），escalated 的报告留痕移到循环外统一渲染。判定能力零改动。

## D2 聚合行 upsert

append_todo_line（core/knowledge_backfill.py:142-182）幂等按整行精确比较（:161-162），动态龄期会逐日追加新行。新增同前缀 upsert 辅助（前缀 = 固定段「audit 疑点升级待人工（聚合）」，匹配即整行替换），core/knowledge_audit.py:1019-1025 的逐条登记改为循环后写一次聚合行。历史逐条行由实现首跑一并替换清理。

## D3 注记格式与红线

页顶格式：H1 与既有 <!-- knowledge: ... --> marker 之后的独立 HTML 注释行 <!-- disputed: since=YYYY-MM-DD fps=<指纹前缀8位列表> -->。
- 不含 knowledge: 前缀：parse_marker/_MARKER_RE 取首个匹配（core/knowledge.py:156-197），disputed 前缀天然不冲突；
- 不引用 archive 路径：audit 悬空清理按行删引用（core/knowledge_audit.py:328-331），注记只带指纹不带链接；
- 150 行硬顶（core/knowledge.py:62,346-350）：涉事 7 页实测 18-31 行余量充足，写入前仍查行数。
写入后走 core/knowledge_audit.py:840-844 的 [fenix] knowledge commit 路径自提交；消费摘除在 R4 同一轮完成。

## D4 仲裁清单

路径 .fenix/knowledge_audit_arbitration.json（.fenix/ 已整体 gitignore，人工本地裁决不入库）。消费挂 escalated-skip 分支：读清单 → 命中指纹且 decision 合法 → _record_verdict（core/knowledge_audit.py:165-184，已具备状态迁移 + 轮次清零）→ 删台账条目 → 摘注记。恢复复核靠既有 entry-is-None 重建（:871-875），零新机制。消费窗口：审计检查点每 300s 检查（fenixd.py:935-942 主循环，内部自然日防重），人工写入后当日生效。

## D5 风险

- 注记与人工编辑冲突：audit 对未提交知识改动有 carryover 告警面（:668-703、:1072-1080），自提交规避。
- 超龄阈值 7 天为建议缺省，配置覆盖沿 core/config.py:2032 的 knowledge 段惯例（非法值回退缺省）。
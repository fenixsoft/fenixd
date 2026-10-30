# code-review-snapshot-writeoff-integrity

## 背景与问题

全仓审查的快照核销（resolve_snapshot，core/code_review.py:1076；坐标经 2026-10-24 评审复核）以「open 且 fingerprint 不在本轮 observed_fingerprints 即置 resolved」为唯一判据，而指纹构成含易变成分：sha1(file|category|normalize_title(title))[:12]（code_review.py:607-613），其中 title 是审查模型每轮重写的中文文案，措辞漂移即换指纹。2026-10-19T18:36:50Z（.fenix/logs/fenixd.log.3:32573；原 fenixd.log 已轮转，该行现位于 .3 分片）代码零变更之夜 resolved=214/updated=0——214 条存量缺陷因指纹零重合被整批假核销（台账 items.jsonl 中 resolution=None、resolved_at 同秒；实测现存恰好 214 条 resolved_at=2026-10-19 且无 resolution 字段的条目），随后 178 条同批缺陷换新指纹重插（inserted=178 同行可证）；次夜 2026-10-20T01:08Z code-fix chain rollup 记 resolved=171（注意：rollup 计数由 mark_resolved 合回命中累积，core/code_fix.py:5929/:7484/:7489，机制上不含快照核销——「假清零计入修复成果」的真实混同面在完成行与 dashboard 展示口径：完成行 core/admin_monitor.py:1918-1925 把 resolved 单值输出，QualityTab 把 resolved 状态统一文案为「已修复」core/dashboard/static/src/pages/projects/components/QualityTab.tsx:125，快照核销与真修复在展示层不可区分）。台账漂移实测（2026-10-24 对 .fenix/code-review/items.jsonl 全量复核）：同文件同类目跨指纹且标题相似度≥0.55 的条目对 228 对（55979 对同组跨指纹对中），最高 0.99（如「has_live_process 中 pid_int 变量赋值后从未使用 / 从未被使用」同缺陷双指纹），漂移是结构性的；evo-add-review-night-defer-snapshot-writeoff 3.2 放宽核销资格（core/agent_runner/maintenance_runs.py:2352-2354）后，该机制每夜可复现，台账面临「夜夜清零、缺陷纹丝不动」的统计失真。

## 目标

1. 核销前对账：未命中指纹的 open 条目先按同文件+类目做归一化标题相似度对账，命中即迁移指纹保持 open，阻断措辞漂移导致的假核销。
2. 核销来源分列：快照核销（snapshot_closed）与合回修复核销（code-fix-auto）在台账字段、完成行、dashboard 统计中分列，杜绝「假清零计入修复成果」。

## 非目标

- 不改指纹算法本身（去 title 会坍缩同文件同类目不同缺陷的粒度；核销时点对账已闭环漂移）。
- 不回填改写存量历史条目（resolution=None 的历史 resolved 按 snapshot_closed 口径解读）。
- 不改 code-fix 链 rollup/进度计数机制：其 resolved/done 由 mark_resolved 真实命中累积（core/code_fix.py:5929/:7484/:7489），机制上不含快照核销，无需改码；SPEC 仅以测试锁定该口径不被破坏。

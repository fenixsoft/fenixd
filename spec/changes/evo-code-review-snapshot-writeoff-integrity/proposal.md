# code-review-snapshot-writeoff-integrity

## 背景与问题

全仓审查的快照核销（resolve_snapshot，core/code_review.py:993）以「open 且 fingerprint 不在本轮 observed_fingerprints 即置 resolved」为唯一判据，而指纹构成含易变成分：sha1(file|category|normalize_title(title))[:12]（code_review.py:524-531），其中 title 是审查模型每轮重写的中文文案，措辞漂移即换指纹。2026-10-19T18:36:50Z（fenixd.log:32573）代码零变更之夜 resolved=214/updated=0——214 条存量缺陷因指纹零重合被整批假核销（台账 items.jsonl 中 resolution=None、resolved_at 同秒），随后 178 条同批缺陷换新指纹重插；code-fix rollup（fenixd.log:32780）把 171 条记入修复成果，dashboard 投影把快照核销与真修复合同口径展示。台账中已实测两对同缺陷双指纹（相似度 0.58/0.66），漂移是结构性的；evo-add-review-night-defer-snapshot-writeoff 3.2 放宽核销资格后，该机制每夜可复现，台账面临「夜夜清零、缺陷纹丝不动」的统计失真。

## 目标

1. 核销前对账：未命中指纹的 open 条目先按同文件+类目做归一化标题相似度对账，命中即迁移指纹保持 open，阻断措辞漂移导致的假核销。
2. 核销来源分列：快照核销（snapshot_closed）与合回修复核销（code-fix-auto）在台账字段、完成行、rollup、dashboard 统计中分列，杜绝「假清零计入修复成果」。

## 非目标

- 不改指纹算法本身（去 title 会坍缩同文件同类目不同缺陷的粒度；核销时点对账已闭环漂移）。
- 不回填改写存量历史条目（resolution=None 的历史 resolved 按 snapshot_closed 口径解读）。
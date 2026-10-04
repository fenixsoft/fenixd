# 回填能力聚合全链蒸馏

<!-- knowledge: capability=knowledge-backfill-chain-aggregation rev=1
     sources=spec/archive/2026-10-05-fix-knowledge-backfill-reconstruction -->

回填车道的蒸馏语义核心：以能力为蒸馏单元，一次读该能力被归档触碰的完整演变链直接写出最终态页面，批次顺序、并行度与断点重入均不影响产出。

## 规则

- 蒸馏单元是能力而非归档：机械扫描全部归档的 `specs/<capability>/spec.md` 目录名，建立「能力 → 触碰它的全部归档 delta（按归档日期升序）」链索引，纯文件系统扫描零 LLM；每个能力派发一次聚合蒸馏 run，LLM 一次读完整链后直接成文。
- 页面产出口径：rev=链长、sources=全链归档、溯源段按日期升序逐行完整；规则段只陈述最终态，早期归档已被覆盖的规则不残留。能力的史前基线（若有）作为链头输入，先读基线再读 delta 链（见史前能力复原）。
- 批次为域内能力集合（批规模上限 ≤20），页间独立：批次执行顺序颠倒、两批并行或断点重入，产出的能力页内容与按日期串行执行完全一致。
- 台账 v2 双维度：`.fenix/knowledge_backfill.jsonl` 条目键 `capability:<能力名>`（能力页蒸馏）与 `adr:<归档名>`（该归档 design.md 的 ADR 抽取扫描），各自携带 pending/distilled/failed。断点重入按两维度独立续跑：已 distilled 条目不重做（真相源无多余改动），failed 重入重试且不阻塞其他条目；收敛汇报分维度给出成败计数。旧归档粒度（v1）台账条目载入即作废，按 v2 重建。
- ADR 抽取批次：主流程对全部 `adr:pending` 条目按归档批次（≤20）派发抽取 run——读该归档 `design.md` 产出/更新 `spec/knowledge/adr/ADR-*.md` 并登记 `adr/index.md`；无 `design.md` 的归档直接标 distilled（留痕跳过，不算失败）。此执行段缺位时 ADR 条目永久 pending，回填收敛判据永不满足，且增量蒸馏排队门不释放。
- 回填期增量蒸馏排队：台账存在 pending 条目期间，`dispatch_distill` 与 `dispatch_distill_batch` 均不派发增量 run，把该归档登记进台账后返回（reason=backfill-queued）——登记时该归档触碰的 capability 条目已为终态的重置为 pending（链索引重扫纳入新归档 delta 后重新聚合，否则新归档溯源行永不落页），adr 条目新建 pending；排队判定或登记故障 fail-open 放行原派发。回填期 `spec/knowledge/` 只有回填车道一个写者；收敛（台账无 pending）后恢复即时派发。

## 溯源

- 2026-10-05 fix-knowledge-backfill-reconstruction（spec/archive/2026-10-05-fix-knowledge-backfill-reconstruction/） — 新增本能力页：链索引与能力聚合成文、批序无关、台账 v2 双维度断点、ADR 抽取批次、回填期增量蒸馏排队单写者

# ADR-234：回填期增量蒸馏排队=台账登记，真相源单写者

date: 2026-10-05
status: accepted

## Context

回填车道从归档粒度改为能力聚合全链蒸馏后，并发写模型出现新风险：回填按能力整链重写页面（一次成文最终态），增量蒸馏按单归档 delta 改页，两者写模型不同。若回填期间归档触发的增量 run 照常并发（先提交者胜），回填刚聚合出的最终态页面可能被只看到部分链的增量 run 部分改写，聚合语义的「批序无关」被并发写破坏。需要排队机制挡住回填期的增量写者，且 daemon 重启不能丢队列。

## Decision

回填台账存在 pending 条目期间，`dispatch_distill` 与 `dispatch_distill_batch` 不派发增量蒸馏 run，把该归档登记进回填台账（capability 条目已终态的重置 pending、adr 条目新建 pending）后返回。排队介质=磁盘台账本身，不做内存队列、不做写者锁；回填收敛判据=台账无 pending 且无 failed 待重试，收敛后恢复即时派发。登记落在 `core.knowledge` 侧、复用台账原子回写（进程间文件锁+按条合并），`core.knowledge_backfill` 顶层不反向 import（仅函数内懒导入）避免导入环。排队判定/登记故障 fail-open 放行原派发，不阻塞归档主流程。

## Consequences

回填期 `spec/knowledge/` 只有回填车道一个写者，页级冲突窗口归零；代价是回填期间新归档的蒸馏可见性延迟到回填收敛之后。台账在盘使排队天然重启安全。排队门依赖 ADR 抽取批次真实执行——adr 条目滞留 pending 时收敛永不满足、增量蒸馏持续被排队，该执行段不可缺。此裁定细化 ADR-230 的并发模型：validate+pathspec 单门与先提交者胜兜底仍在，回填期改为结构性单写者优先。

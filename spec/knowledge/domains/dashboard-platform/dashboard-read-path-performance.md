# 读路径性能治理

<!-- knowledge: capability=dashboard-read-path-performance rev=2
     sources=spec/archive/2026-09-21-fix-dashboard-read-path-performance,spec/archive/2026-10-06-fix-run-cleanup-attach-spec-archive -->

dashboard 读路径的增量失效与有界读取：缓存按 spec 增量重算、run 元数据尾读、runs 清扫有界可审计。

## 规则

- SummaryIndex 失效语义：STATE.md 签名变化时保留既有 spec 缓存条目，仅重算新增的、已删除的、或自身状态/依赖签名发生变化的 spec；仅 STATE 条目字段变化（依赖文件全未变）也必须重算该 spec；全量重建仅用于首次构建与索引损坏场景。
- runs 目录扫描复用：`spec_summary` 复用已预扫描的 `_runs_by_spec_sigs` 映射（每个目录每轮只 glob 一次），MUST NOT 为每个 spec 重新遍历整个 runs 目录；计算 N 个 spec 摘要时 runs 目录 glob 次数为常数。
- run 元数据尾读：`_read_run_lines` 优先从文件尾部按字节窗口 seek 读取，仅窗口内取不全末 N 行（行长超过窗口）时回退全量逐行读取；正确性约束不变——MUST NOT 从行的中间截断导致末行被误解析（避免把已完成 run 误判为 running），回退路径的 `classify_run` 判定与全量读取一致。
- runs 清扫有界可审计：daemon 周期任务把终态 run 产物移入归档，并对归档目录做无主产物按天龄的兜底清理（活跃目录的有界性由「终态即移出」保证，归档目录不设容量上限）；删除记录日志（删除数量与条目名可追溯），单轮删除量有上限或分批，MUST NOT 静默大批量删除。
- watcher 中关于 runs 保留语义的注释与清扫器的实际生效行为保持一致。

## 溯源

- 2026-09-21 2026-09-21-fix-dashboard-read-path-performance（spec/archive/2026-09-21-fix-dashboard-read-path-performance） — SummaryIndex 缓存由「STATE 变化即全丢」改为按 spec 增量失效；runs 目录取消 per-spec 全目录 glob；run 尾读改字节窗口 seek；`runs.keep` 由死键落地为真实归档清理消费点
- 2026-10-06 2026-10-06-fix-run-cleanup-attach-spec-archive（spec/archive/2026-10-06-fix-run-cleanup-attach-spec-archive） — `runs.keep` 消费点已随该归档废除；归档目录清理改为无主产物按天龄兜底（无容量上限），清扫可审计与批次上限约束保留

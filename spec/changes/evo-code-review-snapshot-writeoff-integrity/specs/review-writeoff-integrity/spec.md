# specs/review-writeoff-integrity/spec.md

## R1 核销前对账

resolve_snapshot 置 resolved 前，对未命中 observed_fingerprints 的 open 条目做同 file+category 的归一化标题相似度对账（标准库序列相似度，缺省阈值 0.55）：

- 命中（≥0.55）：视同本轮已观测——把存量条目 fingerprint 迁移为本轮新指纹、保持 open、计 updated，不核销；
- 未命中：按现语义置 resolved，且 resolution 写 'snapshot_closed'（与合回核销 'code-fix-auto' 区分），保留 resolved_at。

## R2 观测记录传递

resolve_snapshot 入参由指纹集合扩展为观测记录集（file/category/title/新指纹）；调用点与框架侧观测集现算（core/agent_runner/maintenance_runs.py:2100-2113、:2115）同口径传递。

## R3 完成行分列

审查完成行把 resolved 拆为 snapshot_closed 与 fixed 两个计数分别输出。

## R4 消费口径分列

- code-fix rollup 与进度 done 累计只统计 resolution='code-fix-auto' 的核销，snapshot_closed 不入修复成果；
- dashboard 台账投影透出 resolution 字段，修复/龄期统计按来源分列；
- 存量 resolution=None 的历史 resolved 条目按 snapshot_closed 口径解读，不回填改写。

## R5 安全边界

相似度低于阈值不得误保（避免把真消失的缺陷永久挂在 open）；对账只在快照核销路径生效，不影响合回核销与人工处置路径。
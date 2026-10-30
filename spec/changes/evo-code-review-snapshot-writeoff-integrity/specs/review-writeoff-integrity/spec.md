# specs/review-writeoff-integrity/spec.md

## R1 核销前对账

resolve_snapshot 置 resolved 前，对未命中 observed_fingerprints 的 open 条目做同 file+category 的归一化标题相似度对账（标准库序列相似度，缺省阈值 0.55）：

- 命中（≥0.55）：视同本轮已观测——把存量条目 fingerprint 迁移为本轮新指纹、保持 open、计 updated，不核销；
- 对账 1:1 领用：一条观测记录至多对账一条存量条目（相似度最高者优先，并列取 last_seen_at 更近者），被领用的观测不得再对账其他条目；
- 迁移去重：本轮 upsert 已插入同新指纹的 open 孪生条目时，迁移 MUST 合并——保留存量条目（item_id/first_seen_at 稳定）并以观测记录刷新其展示字段、删除孪生；同一 fingerprint 在台账中至多一条条目；
- 未命中（含放弃迁移）：按现语义置 resolved，且 resolution 写 'snapshot_closed'（与合回核销 'code-fix-auto' 区分），保留 resolved_at。

## R2 观测记录传递

resolve_snapshot 入参由指纹集合扩展为观测记录集（file/category/title/新指纹）；调用点与框架侧观测集现算（core/agent_runner/maintenance_runs.py:2445-2457、:2459）同口径传递。

## R3 完成行分列

审查完成行把 resolved 拆为 snapshot_closed 与 fixed 两个计数分别输出：resolve_snapshot 返回拆分计数 → CodeReviewResult（core/agent_runner/result_gate.py:367）携带 → core/admin_monitor.py 完成行（:1918-1925）输出两计数。

## R4 消费口径分列

- code-fix 链 rollup 与进度 done 只统计 mark_resolved 合回核销（既有机制，core/code_fix.py:5929/:7484/:7489），snapshot_closed 不入修复成果——以测试锁定该口径，不改码；
- dashboard 台账投影透出 resolution 字段，resolved 条目按来源展示（code-fix-auto=已修复 / snapshot_closed=快照关闭 / 缺失按快照关闭口径解读），已修复统计按来源分列；
- 存量 resolution=None 的历史 resolved 条目按 snapshot_closed 口径解读，不回填改写。

## R5 安全边界

相似度低于阈值不得误保（避免把真消失的缺陷永久挂在 open）；对账只在快照核销路径生效，不影响合回核销与人工处置路径；对账迁移不得造成台账同指纹重复条目（孪生合并），不得使任何缺陷脱离台账跟踪（孪生非 open 时放弃迁移、按未命中语义核销）。

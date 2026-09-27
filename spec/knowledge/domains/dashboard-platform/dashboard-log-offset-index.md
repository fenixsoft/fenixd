# 日志偏移索引

<!-- knowledge: capability=dashboard-log-offset-index rev=1
     sources=spec/archive/2026-09-09-add-dashboard-incremental-data -->

fenixd 结构化日志的块偏移索引：时间轴与事件查询只读尾部窗口，不再全量扫描日志文件。

## 规则

- 为 `.fenix/logs/fenixd*.log` 维护 `.fenix/logs/.idx/` 块偏移索引，记录 `{size, blocks:[每 64KB 块首行偏移]}`。
- `get_spec_timeline` 与 `get_recent_events` 由索引定位读取段：只读目标窗口对应的块段（尾部 ≤1MB），不全量读文件；查询结果与全量扫描口径一致（事件内容与顺序相等）。
- 索引热更新：日志追加新行后索引追加推进到新 size（追加场景重建次数为 0），新行可被查询到。
- 索引损坏容错：索引文件缺失或 size 与日志不符（如日志被截断轮转）时查询不报错——重建索引（≤1 次全量扫描）后返回正确结果，后续沿用新索引。
- 窗口截断语义：查询点早于索引覆盖窗口（尾部 1MB 内 16 块 + 1 个身位）的部分不追溯，返回窗口内最近内容即可（可少于全量），不抛错不阻塞；前端时间轴按「最近 N 条」展示，不要求完整历史。

## 溯源

- 2026-09-09 2026-09-09-add-dashboard-incremental-data — 建立日志块偏移索引与窗口截断语义，时间轴/事件查询从全量扫描（7.5MB，万级 spec 时 700MB）改为只读尾部 1MB 窗口

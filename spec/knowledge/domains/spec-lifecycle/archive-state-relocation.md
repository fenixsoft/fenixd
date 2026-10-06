# 归档条目迁出与归档清单
<!-- knowledge: capability=archive-state-relocation rev=1
     sources=spec/archive/2026-10-06-add-archive-state-migration -->

SPEC 归档后把 STATE.md 条目迁出到归档清单 `.fenix/STATE.archive.md`：STATE.md 收敛为活跃条目集合，已归档条目在清单中长期可查、可审计。

## 规则

- 归档清单 `.fenix/STATE.archive.md` 与 STATE.md 同格式（`### <spec名>` 小节 + `- key: value` 字段行），共用同一套解析逻辑；文件不存在视为空清单，读侧与迁出侧均不报错，首次迁出即创建。
- 条目迁出时追加两个溯源字段：`archived_at`（迁出时刻，UTC ISO 8601）与 `archived_by`（迁出路径，取值 `auto`/`ui`/`cli`/`backfill` 之一）。
- 清单只经三类写操作变更：迁出追加、同名条目幂等覆盖（整体重写消除重复小节）、软删除移除；活跃 STATE.md 的任何状态流转都不重写清单（内容与 mtime 均不变）。
- 迁出原语（StateMachine 方法）在 STATE.md 既有 flock 文件锁内原子完成两步：先把条目（含溯源字段）追加写入清单，再重写 STATE.md 移除该条目。顺序保证崩溃窗口只可能出现「清单已有 + 活跃仍有」的双源中间态（读侧活跃优先、回填下轮收敛），绝不出现「活跃已删 + 清单没有」的丢条目态。
- 清单写入失败（OSError 等）时迁出返回失败、STATE.md 不动（条目不丢，无半迁出状态）；SPEC 不在 STATE.md 时返回未找到语义（幂等：重复迁出不报错、不改清单）。
- 三条归档路径在目录成功移入 `spec/archive/` 后自动调用迁出原语：daemon 自动归档记 `auto`、Dashboard 归档 API 记 `ui`、`bin/fenix_archive.py` skill 记 `cli`。归档移动失败或被拒绝（非终态、目标已存在）时不迁出。迁出失败降级为归档结果的告警字段，不回滚目录移动、不阻断归档主流程返回。
- 存量回填：daemon 周期扫描活跃 STATE.md 中「终态且活跃目录 `spec/changes/<name>/` 已不存在」的条目逐个迁出（`archived_by=backfill`），先回填后阈值归档。回填幂等可安全重复（已迁出条目自然退出扫描集）；单条失败跳过记日志、不中断；与归档阈值开关无关（`archive.auto_threshold` 设 0 时仍执行）。非终态条目即使活跃目录缺失也不迁出（异常态留人工排查，日志记录跳过）。
- 统计口径只算活跃：Dashboard 概览与项目摘要统计（spec_count、task_done/task_total、problems、状态分布等）仅基于活跃 STATE.md 条目，已迁出条目不计入。SPEC 详情（文档、任务清单、时间轴）对已迁出 SPEC 继续可用（经既有归档目录回退读取）。
- 双源读侧消费方一律活跃优先：evo 候选 SPEC 名去重并入清单键集（防止已迁出 SPEC 名被重复占用后归档目录命中歧义）；软删除的 `found` 判定含清单，对条目已迁出的 SPEC 同步清除清单条目与归档目录（双源并存中间态则两处都清），清单小节移除与迁出写侧同锁（`.STATE.md.lock` flock 内），避免与并发迁出/回填竞态。

## 溯源

- 2026-10-06 add-archive-state-migration（spec/archive/2026-10-06-add-archive-state-migration） — 新增归档条目迁出机制：STATE.archive.md 归档清单与溯源字段、flock 内先清单后活跃迁出原语、三条归档路径收口、幂等存量回填、统计活跃口径与软删除/evo 撞名双源兼容

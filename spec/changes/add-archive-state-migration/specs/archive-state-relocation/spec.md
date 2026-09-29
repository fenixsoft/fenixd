## ADDED Requirements

### Requirement: 归档清单文件

系统 SHALL 使用 `.fenix/STATE.archive.md` 作为已迁出 SPEC 条目的归档清单：文件格式与 STATE.md 相同（`### <spec名>` 小节 + `- key: value` 字段行），可被同一解析逻辑读取。条目迁出时系统 SHALL 在该条目追加两个溯源字段：`archived_at`（迁出时刻，UTC ISO 8601 字符串）与 `archived_by`（迁出路径，取值 `auto`/`ui`/`cli`/`backfill` 之一）。清单文件 SHALL 只经三类写操作变更：追加（迁出）、同名条目幂等覆盖（迁出原语去重，以整体重写消除重复小节）与移除（软删除），SHALL NOT 因活跃 STATE.md 的任何状态流转被重写。清单文件不存在时 SHALL 视为空清单（读侧与迁出侧均不报错）。

#### Scenario: 迁出条目落入清单并带溯源字段

- **WHEN** 某 SPEC 经任一归档路径迁出 STATE.md
- **THEN** `.fenix/STATE.archive.md` 出现该 SPEC 的小节，字段与迁出前 STATE.md 条目一致，且含 `archived_at` 与 `archived_by`

#### Scenario: 清单缺失视为空

- **WHEN** 项目尚无 `.fenix/STATE.archive.md`，读侧解析清单或执行迁出
- **THEN** 解析返回空 dict，首次迁出创建该文件，不抛错

#### Scenario: 活跃状态流转不重写清单

- **WHEN** 任一活跃 SPEC 状态流转触发 STATE.md 全量重写
- **THEN** `.fenix/STATE.archive.md` 内容与 mtime 均不变

### Requirement: 迁出原语原子性

系统 SHALL 提供迁出原语（StateMachine 方法）：在 STATE.md 既有 flock 文件锁内原子完成「从 STATE.md 移除该条目 + 将该条目（含溯源字段）追加写入归档清单」两步。清单写入失败（OSError 等）时 SHALL 保持条目留在 STATE.md 并返回失败（条目不丢）；SPEC 不在 STATE.md 时 SHALL 返回未找到（幂等，迁出已迁出的 SPEC 不报错、不改清单）。迁出后 STATE.md 中 SHALL 不再含该条目。

#### Scenario: 迁出后活跃条目消失且清单新增

- **WHEN** 对 STATE.md 中存在的终态 SPEC 调用迁出原语
- **THEN** STATE.md 重写后不含该条目，清单文件含该条目（含溯源字段）

#### Scenario: 清单写入失败条目不丢

- **WHEN** 清单文件写入抛出 OSError（如目录只读），迁出原语执行
- **THEN** 原语返回失败，STATE.md 中该条目原样保留，无半迁出状态

#### Scenario: 重复迁出幂等

- **WHEN** 对已迁出（STATE.md 无条目）的 SPEC 再次调用迁出原语
- **THEN** 返回未找到语义，清单文件不变，不报错

### Requirement: 归档成功即迁出

三条归档路径（daemon 自动归档、Dashboard 归档 API、`bin/fenix_archive.py` skill）在归档移动成功（目录已移入 `spec/archive/`）后 SHALL 自动调用迁出原语迁出该 SPEC 的 STATE.md 条目；`archived_by` SHALL 分别记为 `auto`、`ui`、`cli`。归档移动失败或被拒绝（非终态、目标已存在）时 SHALL NOT 迁出。迁出失败 SHALL 降级为归档结果的告警字段（不回滚目录移动、不阻断归档主流程返回）。

#### Scenario: 归档成功条目即迁出

- **WHEN** 任一归档路径对终态 SPEC 归档成功
- **THEN** 该 SPEC 条目从 STATE.md 消失并出现在清单，`archived_by` 对应该路径

#### Scenario: 归档被拒绝不迁出

- **WHEN** 归档因目标已存在被拒绝
- **THEN** STATE.md 条目与清单均不变

#### Scenario: 迁出失败降级告警

- **WHEN** 归档成功但迁出原语失败
- **THEN** 归档结果仍为成功，附加迁出告警字段，日志记录告警

### Requirement: 幂等存量回填

daemon SHALL 周期执行存量回填：扫描活跃 STATE.md 中「活跃目录 `spec/changes/<name>/` 已不存在」（即已归档但条目未迁出）的条目，逐个迁出，`archived_by` 记为 `backfill`。回填 SHALL 可安全重复执行（已迁出的条目自然不在扫描集内）；单条迁出失败 SHALL 跳过并记日志，不中断回填；回填 SHALL 与归档阈值无关（不依赖 `auto_threshold` 配置，阈值设 0 时回填仍执行）。非终态条目即使活跃目录缺失 SHALL NOT 被回填迁出（异常态保留人工排查）。

#### Scenario: 存量已归档条目被批量迁出

- **GIVEN** STATE.md 存在多条终态且活跃目录已不存在的条目（历史归档遗留）
- **WHEN** daemon 执行回填
- **THEN** 这些条目全部迁出清单（archived_by=backfill），STATE.md 仅剩活跃目录存在或非终态的条目

#### Scenario: 回填幂等可重复

- **WHEN** 回填连续执行两轮
- **THEN** 第二轮扫描集为空，清单无重复条目

#### Scenario: 非终态孤儿条目保留

- **WHEN** 某非终态 SPEC 的活跃目录缺失（异常态）
- **THEN** 回填不迁出该条目，日志记录跳过

### Requirement: 统计口径只算活跃

Dashboard 概览与项目摘要统计（spec_count、task_done/task_total、problems、状态分布等）SHALL 仅基于活跃 STATE.md 条目计算，已迁出条目 SHALL NOT 计入。SPEC 详情读取（文档、任务清单、时间轴）对已迁出 SPEC SHALL 继续可用（经既有归档目录回退）。

#### Scenario: 迁出后统计数字下降

- **WHEN** 某 SPEC 被归档迁出后请求 Overview 统计
- **THEN** spec_count 与任务总数较迁出前减少该 SPEC 的计入值，且不含该 SPEC

#### Scenario: 迁出后详情仍可读

- **WHEN** 用户从「已归档」视图打开某已迁出 SPEC 的详情页
- **THEN** proposal/design/tasks 等文档正常展示（读自归档目录），任务进度与迁出前一致

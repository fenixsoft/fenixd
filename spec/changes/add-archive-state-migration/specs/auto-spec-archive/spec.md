## MODIFIED Requirements

### Requirement: daemon 周期检查并执行自动归档

daemon 主循环 SHALL 周期性（独立低频计时，量级为分钟级）对每个项目执行自动归档检查：统计状态为 done/pushed 且未归档（`spec/changes/<name>/` 目录仍存在）的 SPEC 数量；超过有效阈值时，按完成时间从最久到最新依次归档（调用与手动归档相同的移动逻辑：目录移入 `spec/archive/YYYY-MM-DD-<name>/`），且每条归档成功后 SHALL 迁出该 SPEC 的 STATE.md 条目至归档清单（`archived_by=auto`；迁出失败降级告警，条目留待存量回填），直到未归档终态数量降至阈值以内。有效阈值（`ConfigLoader.effective_auto_archive_threshold`，缺省 50）为 0 时 SHALL 跳过检查（存量回填不受此开关约束，先回填后阈值归档）。完成时间 SHALL 取 STATE.md 条目的 updated 字段（终态 SPEC 不再更新，updated 即完成时间）。单个 SPEC 归档失败（如目标目录已存在）SHALL 跳过该条并继续处理其余，且记录日志，不中断检查循环。

#### Scenario: 超阈值自动归档最久完成的

- **GIVEN** 某项目 auto_threshold=2，存在 4 个终态 SPEC，完成时间 A<B<C<D
- **WHEN** daemon 执行自动归档检查
- **THEN** A、B 被归档（目录移入 archive/ 且条目迁出清单），C、D 保留，数量降至阈值以内

#### Scenario: 归档成功条目同步迁出

- **GIVEN** 某项目终态 SPEC 数量超过阈值
- **WHEN** daemon 自动归档某 SPEC 成功
- **THEN** 该 SPEC 条目从 STATE.md 消失并出现在清单，archived_by=auto；后续轮次不再统计该条目

#### Scenario: 未超阈值不动作

- **GIVEN** 某项目终态 SPEC 数量未超过阈值
- **WHEN** daemon 执行自动归档检查
- **THEN** 不移动任何目录、不迁出条目，日志无归档动作

#### Scenario: 阈值为 0 时禁用

- **GIVEN** 某项目 archive.auto_threshold=0
- **WHEN** daemon 执行检查
- **THEN** 跳过该项目，不做任何归档迁出（存量回填仍独立执行）

#### Scenario: 单条失败不阻塞

- **GIVEN** 待归档队列中最久一条的归档目标目录已存在
- **WHEN** daemon 执行自动归档
- **THEN** 该条被跳过并记录日志，其余符合条件的 SPEC 正常归档迁出

#### Scenario: 非终态与已归档不计入阈值

- **GIVEN** 某项目有 3 个终态未归档 SPEC、2 个 implementing、1 个已归档终态
- **WHEN** 阈值为 3 时执行检查
- **THEN** 数量为 3 未超阈值，无归档动作（implementing 与已归档条目不计入）

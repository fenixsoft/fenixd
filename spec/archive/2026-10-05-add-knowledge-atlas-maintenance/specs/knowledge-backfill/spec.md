## ADDED Requirements

### Requirement: 存量归档批量回填

框架 SHALL 提供存量回填车道：遍历 `spec/archive/` 下全部归档 SPEC（前置 SPEC 上线前累积的 300 个），按蒸馏管线同一契约批量产出真相源。首轮回填 run SHALL 完成域骨架自举（agent 自动聚类全部归档的能力 → 产出域清单、`index.md` 与各域 `_domain.md`），后续批次按域归位逐批蒸馏。回填进度 SHALL 落运行时台账（`.fenix/` 下），每归档记录 pending/distilled/failed 状态，支持中断重入：重跑时只处理 pending 与 failed 条目。

#### Scenario: 中断后重入不重做已完成批次

- **WHEN** 回填执行到第 3 批被中断（前 2 批已提交），随后再次触发回填
- **THEN** 进度台账中前 2 批对应归档为 distilled，重入只派发第 3 批起未完成条目，已蒸馏归档不被重复处理（真相源无重复改动）

#### Scenario: 单批失败不阻塞后续批次

- **WHEN** 某批蒸馏 run 校验两轮仍失败
- **THEN** 该批条目标 failed 并登记 todo.md，后续批次照常派发；最终汇报含 failed 清单

### Requirement: 批间确定性校验与提交

每批回填产落盘前 SHALL 经 `validate_knowledge` 全量校验（与增量蒸馏同一标准，含 150 行硬顶与溯源链接存在性），通过后以 pathspec 限定 `spec/knowledge/` 提交（commit 形如 `[fenix] knowledge: backfill batch <N>/<total>`）。单批 SHALL 控制规模（每批归档数有上限，实现裁量建议 ≤20）以限制单次 run 爆炸半径。

#### Scenario: 批次提交可独立回溯

- **WHEN** 回填全部完成
- **THEN** git 历史中每批一个提交（形如 `[fenix] knowledge: backfill batch N/total`），任一批可单独回滚而不影响其他批

#### Scenario: 回填产物与增量产物同标准

- **WHEN** 对回填完成的真相源运行 validate_knowledge
- **THEN** 零违规（marker、溯源链接、行数硬顶、链接可解析全部通过）

### Requirement: 回填完成收敛与汇报

回填车道 SHALL 在全部条目 distilled 或 failed 时收敛，产出汇报（总批数、成功/失败数、失败清单、真相源最终规模：域数/能力页数/ADR 数）。收敛后自动回填车道不再重复触发（幂等），仅当出现新的未回填归档（如增量蒸馏曾失败入台账）时才重入处理增量。

#### Scenario: 收敛汇报可读

- **WHEN** 回填车道收敛
- **THEN** 产出汇报含批次总数、成功/失败计数、失败条目清单（指向 todo.md）、真相源最终规模统计

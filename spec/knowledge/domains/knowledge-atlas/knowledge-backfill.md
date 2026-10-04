# 存量归档批量回填车道

<!-- knowledge: capability=knowledge-backfill rev=1
     sources=spec/archive/2026-10-05-add-knowledge-atlas-maintenance -->

把真相源机制上线前累积的存量归档批量回流进 `spec/knowledge/` 的批处理车道，产出与增量蒸馏同一标准的真相源页。

## 规则

- 覆盖范围：遍历 `spec/archive/` 下全部归档 SPEC，按域聚类分批蒸馏。首轮回填 run 先做域骨架自举——读全部归档的 specs/ 目录名与 proposal 标题，自动聚类产出域清单与 `index.md`、各域 `_domain.md` 骨架；后续批次按域归位逐批蒸馏。能力→域的机器可读归位清单落 `.fenix/knowledge_backfill_domains.json`。
- 进度台账：`.fenix/knowledge_backfill.jsonl` 每归档一行（name/status/batch/updated_at），状态三态 pending/distilled/failed。车道支持中断重入：重跑只派发 pending 与 failed 条目，已 distilled 归档不重复处理，真相源无重复改动。
- 批间校验与提交：每批落盘前经 `validate_knowledge` 全量校验（与增量蒸馏同一标准、零豁免——marker、溯源、150 行硬顶、链接可解析全部通过），通过后以 pathspec 限定 `spec/knowledge/` 提交，commit 形如 `[fenix] knowledge: backfill batch <N>/<total>`，任一批可独立回滚而不影响其他批。
- 批规模：每批归档数有上限（≤20），限制单次 run 的爆炸半径。单批校验两轮仍失败时，该批条目标 failed 并登记 todo.md，不阻塞后续批派发；重做只针对失败条目，不重做整批。
- 收敛与幂等：全部条目 distilled 或 failed 即收敛，产出汇报——总批数、成功/失败计数、失败清单（指向 todo.md）、真相源最终规模（域数/能力页数/ADR 数）。收敛后自动回填不再重复触发，仅当出现新的未回填归档（如增量蒸馏失败入台账）时才重入处理增量。
- 与增量蒸馏并发：回填期间归档触发的增量蒸馏照常运行，两者写同一真相源。并发写由 validate_knowledge + pathspec 限定提交保证原子：页级冲突先提交者胜，后启动的蒸馏 run 启动时重读现网真相源、基于新版自然叠加，无脏写窗口。

## 溯源

- 2026-10-05 add-knowledge-atlas-maintenance（spec/archive/2026-10-05-add-knowledge-atlas-maintenance） — 新增本能力页：域骨架自举、台账断点续跑、批间校验与 pathspec 提交、批规模上限、收敛汇报幂等、与增量蒸馏的并发写契约

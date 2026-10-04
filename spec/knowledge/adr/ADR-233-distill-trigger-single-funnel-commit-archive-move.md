# ADR-233：蒸馏触发单点挂载归档共同漏斗 commit_archive_move

date: 2026-10-05
status: accepted

## Context

SPEC 归档有多条路径：手工/CLI（`.fenix/bin/fenix_archive.py`，gitignored 不可交付）、daemon 自动归档（`auto_archive_check` 周期调用 `spec_archive.archive_spec`）、软删除（以归档移动收尾）。逐路径挂蒸馏触发会漂移漏挂，且手工脚本不可作为 SPEC 交付物。

## Decision

蒸馏派发单点挂在 `core/archive_commit.py::commit_archive_move` 移动成功分支——三条路径已全部漏斗经过该函数，单点挂载即全部生效；后续新增归档路径必须沿用该漏斗，否则视为放弃蒸馏。派发 fail-open：异常只记日志与重试台账，不影响归档返回值；`knowledge.enabled=false` 直接跳过。直接调用 `commit_archive_move` 的既有单测经 dispatch 注入替身隔离，不触发真实派发。

## Consequences

任何归档动作自动获得蒸馏，无双写、无漏挂；不可交付的运行时脚本无需触碰。代价：软删除也触发蒸馏（预期行为，其目录同样落 `spec/archive/`、sources 存在性校验天然兼容）；漏斗本身成为关键路径，对其改签名/行为时须同时核对蒸馏车道。

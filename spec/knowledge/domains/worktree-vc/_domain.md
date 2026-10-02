# 工作树与版本控制
> 最后更新：2026-10-03 04:59 UTC+8

实现工作树（worktree）的隔离、播种、回读与卫生，实现分支合回主树与推送的完整生命周期纪律。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [worktree-isolation](worktree-isolation.md) | worktree 隔离（Popen cwd 隔离） | 2026-10-03 04:59 |
| [worktree-spec-seeding](worktree-spec-seeding.md) | worktree SPEC 播种 | 2026-10-03 04:59 |
| [worktree-result-readback](worktree-result-readback.md) | worktree 结果回读 | 2026-10-03 04:59 |
| [worktree-hygiene](worktree-hygiene.md) | worktree 卫生与复用 | 2026-10-03 04:59 |
| [run-isolation](run-isolation.md) | run 工作树隔离与冲突恢复 | 2026-09-27 22:14 |
| [merge-back](merge-back.md) | merge-back 合并回主树 | 2026-10-03 04:59 |
| [merge-back-precheck](merge-back-precheck.md) | merge-back 预检（WIP 交集升级拦截） | 2026-10-03 04:59 |
| [wip-defer-merge-retry](wip-defer-merge-retry.md) | WIP 阻断延迟合回（等待标志 + 周期自动合回） | 2026-10-03 04:59 |
| [merge-circuit-breaker](merge-circuit-breaker.md) | merge 熔断（失败指纹） | 2026-10-03 04:59 |
| [merge-rehearsal](merge-rehearsal.md) | 合并预演与语义冲突直通修复 | 2026-10-03 04:59 |
| [merge-untracked-guard](merge-untracked-guard.md) | 未跟踪文件合并守卫 | 2026-10-03 04:59 |
| [mergeback-inplace-repair](mergeback-inplace-repair.md) | merge-back 原位修复（repair 车道） | 2026-10-03 04:59 |
| [mergeback-stashpop-self-heal](mergeback-stashpop-self-heal.md) | stash pop 自愈 | 2026-10-03 04:59 |
| [stashpop-conflict-treatment](stashpop-conflict-treatment.md) | stash pop 冲突处置 | 2026-10-03 04:59 |
| [push-ref-hygiene](push-ref-hygiene.md) | 推送引用生命周期卫生 | 2026-10-03 04:59 |

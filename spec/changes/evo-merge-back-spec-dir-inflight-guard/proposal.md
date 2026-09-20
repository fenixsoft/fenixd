# merge-back-spec-dir-inflight-guard

## Why

**已成功的实现 run 因 merge-back 撞上「spec 目录在飞编辑」而整轮作废，重做后再合入，单 spec 累计 $14.91。**

2026-09-19 实证（本 SPEC 立项的直接触发）：evo-transient-storm-alert-context 首次实现 run（impl-evo-transient-storm-alert-context-1789773909）已成功收工（117 轮、3869 秒、$8.97），merge-back 时因主树 spec/changes/evo-transient-storm-alert-context/tasks.md 存在未提交改动（spec 迭代提交之间在飞编辑）被判「本地改动将被 merge 覆盖」而拒绝（fenixd.log 2026-09-19T00:29:39Z「Self-heal (identical) aborted」+「Merge failed … would be overwritten by merge」）。两条分支提交（bb2657c0、da135958）未入 main；约 11 分钟后（00:40:25）系统重新派发实现**整轮**（impl-…-1789778425，88 轮、$5.94）后才合入。$8.97 与约 1 小时为纯无产出消耗。

根因：merge-back 失败后 pm_engine 把 spec 回置 ready 并计入 Retry N/3（core/pm_engine/dispatch/queue.py），orphan recovery 每分钟 re-trigger「implementer_run preserved」，等待窗口约 11 分钟后仍重新派发实现**整轮**——而不是「保留已成功分支，等待主树干净后仅重试合并」。且 merge-back 前对 spec/changes/ 目录的**在飞未提交编辑**没有任何卫检查：Self-heal 检测到「tasks.md differs from branch content」仅告警即中止，merge 仍被拒、整轮重做。

本 SPEC 补两条机制：

1. **merge-back 前卫检查**：merge-back 前对 spec/changes/ 目录做在飞未提交编辑检测，命中即顺延等待提交（对齐 evo-recovery-watch-status-recheck 的顺延范式），不进入 merge；
2. **merge-back 失败分类**：区分「可重试（主树脏 / spec 在飞编辑 / 锁冲突）」与「run 真失败」——可重试时保留已成功分支与产物、等待主树干净后**仅重试合并**，等待/重试不消耗实现尝试预算（used count），不重派实现整轮。

与既有机制的关系：evo-merge-back-wip-overlap-gate（2026-09-02 归档）覆盖「主树 WIP 与分支重叠」的 stash 形态；add-merge-back-repair-lane（2026-09-09 归档）覆盖「merge 语义冲突」的原地修复；本 SPEC 覆盖「spec 目录被外部在飞编辑」这一未覆盖变体。
# merge-back-spec-dir-inflight-guard

## Why

**已成功的实现 run 因 merge-back 撞上「spec 目录在飞编辑」而整轮作废，重做后再合入，单 spec 累计 $14.91。**

2026-09-19 实证（本 SPEC 立项的直接触发）：evo-transient-storm-alert-context 首次实现 run（impl-evo-transient-storm-alert-context-1789773909）已成功收工（117 轮、3869 秒、$8.97），merge-back 时因主树 spec/changes/evo-transient-storm-alert-context/tasks.md 存在未提交改动（spec 迭代提交之间在飞编辑）被判「本地改动将被 merge 覆盖」而拒绝（fenixd.log 2026-09-19T00:29:39Z「Self-heal (identical) aborted」+「Merge failed … would be overwritten by merge」）。两条分支提交（bb2657c0、da135958）未入 main；约 11 分钟后（00:40:25）系统重新派发实现**整轮**（impl-…-1789778425，88 轮、$5.94）后才合入。$8.97 与约 1 小时为纯无产出消耗。

根因：merge-back 失败后 pm_engine 把 spec 回置 ready 并计入 Retry N/3（core/pm_engine/dispatch/queue.py），orphan recovery 每分钟 re-trigger「implementer_run preserved」，等待窗口约 11 分钟后仍重新派发实现**整轮**——而不是「保留已成功分支，等待主树干净后仅重试合并」。且 merge-back 前对 spec/changes/ 目录的**在飞未提交编辑**没有任何卫检查：Self-heal 检测到「tasks.md differs from branch content」仅告警即中止，merge 仍被拒、整轮重做。

本 SPEC 补两条机制：

1. **merge-back 前卫检查**：merge-back 前对 spec/changes/ 目录做在飞未提交编辑检测，命中即顺延等待提交（对齐 evo-recovery-watch-status-recheck 的顺延范式），不进入 merge；
2. **merge-back 失败分类**：区分「可重试（主树脏 / spec 在飞编辑 / 锁冲突）」与「run 真失败」——可重试时保留已成功分支与产物、等待主树干净后**仅重试合并**，等待/重试不消耗实现尝试预算（used count），不重派实现整轮。

与既有机制的关系：evo-merge-back-wip-overlap-gate（2026-09-02 归档）覆盖「主树 WIP 与分支重叠」的 stash 形态；add-merge-back-repair-lane（2026-09-09 归档）覆盖「merge 语义冲突」的原地修复；本 SPEC 覆盖「spec 目录被外部在飞编辑」这一未覆盖变体。

**有界性（MUST，与「不重派」目标同等重要）**：两条机制都**必须设硬上限**。原事故之所以收敛，是因为约 11 分钟后系统重新派发实现整轮；若把该重派换成**无上限**的顺延等待，则变成「spec 永不再被处理」——比事故更差（原事故至少收敛）。故：顺延窗口固化（缺省 30 分钟）+ 顺延轮数上限（缺省 3 轮），超限回落既有「告警 + 等待人工处置」通道；且上限 MUST 先于实现预算（`agents.impl_run_budget`，缺省 6）耗尽收敛。取证（库内提交通道清点）：**没有任何通道会为「已 ready / implementing 的在飞 spec」提交 spec/changes**——`ensure_spec_committed` 只在派发实现前调用（queue.py:831）、`_sync_task_progress` 只在 merge 成功后调用（queue.py:1465）且工作树脏时直接跳过（engine.py:1535-1538）；故顺延的解除者与上限均须在 design/tasks 中显式点名（见 design D1a），不得留给实现者。
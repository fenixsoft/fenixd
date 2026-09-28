# ADR-197：WIP 阻断延迟合回——暂态零预算、保留现场必放锁、重试挂链节拍

date: 2026-09-29
status: accepted

## Context

code-fix 批车道把 merge-back 的 WIP 重叠预检阻断（`wip_gate_blocked=True`）当普通合回冲突消费：整批现场即弃、条目入失败档案烧 `fail_count`、下轮重跑整个 agent。实证（2026-09-23）批 21/22 连续「合回冲突，现场即弃」，各烧约 40 分钟 agent 产出，而 `git merge-tree` 证实两分支与主树 HEAD 内容合并零冲突——纯粹是主树 tracked-modified 挡路的可等待自愈暂态。既有的失败纪律（ADR-167：失败现场即弃+锁即时释放）与 ADR-175（批收尾必释放 worktree 锁）都以「批已死」为前提，没有给「产物已提交、只差合回」的暂态留出口；直接照搬会持续烧预算重做注定成功的修复。

## Decision

- **暂态阻断与确定性失败生命周期分离**：`wip_gate_blocked=True` 的批不进失败档案、不烧 `fail_count`，走独立 defer 台账（`.fenix/code-review/fix-deferred.json`，与 `fix-failed.json` 物理分离——两者生命周期相反：失败档案烧预算期待重跑，defer 队列零预算期待原地合回，混写会让释放逻辑误伤 defer 条目）。后续任何「可等待自愈的暂态」同样禁止接入失败预算体系：预算体系的语义是「重跑」，暂态需要的只是「等待」。
- **保留现场与放行车道同生同灭**：defer 保留 worktree 目录、分支与活动集在册的同时，MUST 显式释放 `code-review-fix:code-fix` spec 锁（worktree lifecycle 新增最小公开原语 `release_spec_lock`，只清锁与 lock_since，不动目录/分支/活动集）。只跳过 cleanup 而不放锁，同键 `create()` 恒返回 None、批 worker 走 halt——defer 后下一批建树必败，整条车道在主树脏期间死锁，比即弃更糟。
- **defer 条目必须退出选批池**：台账 `item_ids` 并入 `select_batch` 排除集。defer 条目在合回成功前始终 open 且不在失败档案，不排除会被下一边界 earliest-first 立即重选、重跑 agent，defer 收益归零。
- **重试挂既有链节拍，不新增线程**：重试时机只有两个——批边界选批之前与链收敛出口之前，均在 checkpoint 锁段内（批在飞时 checkpoint `already_running` 早退，天然与在飞批互斥）。不新增定时器/线程，规避调度复杂度与重启孤儿。

## Consequences

- worktree_manager 的锁生命周期与目录/分支/活动集生命周期正式解耦：后续任何「保留现场」类语义一律走 `release_spec_lock` 原语，不再借 cleanup 路径变通。
- 放锁后同键可并存第二个 worktree，其安全前提是重试点与在飞批的锁段互斥；新增绕过 checkpoint 锁段的重试点会引入并发风险。
- 台账与磁盘可能漂移（手删 worktree 等），靠新链启动再认领核对磁盘收敛；defer 期间占盘由预算双门（90 分钟 / 6 次实际尝试）强制收敛，降级路径必清理。
- 主树长期不清理时，每个延迟批 90 分钟后连环降级烧失败档案——有意为之：defer 只豁免暂态等待期，不豁免人工不处置；首次 defer 即发 info 提示，把处置责任及时交还人工。

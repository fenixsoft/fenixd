# design: merge-back-spec-dir-inflight-guard

## D1 卫检查：spec/changes 在飞编辑检测

- 位置：core/worktree_manager/mergeback.py merge_back_from_branch 入口（_wip_overlap_gate 同级）。
- 实现：git status --porcelain 限定 spec/changes/ 目录检测未提交改动，命中即返回顺延信号（reason=spec_dir_inflight），不触发 merge；调用方（core/pm_engine/dispatch/queue.py）识别后重排等待而非失败。
- 顺延范式对齐 evo-recovery-watch-status-recheck：等待下一次 recovery/心跳时点重试，由主树提交动作解除，不新增硬超时上限。

## D2 失败分类与仅重试合并

- 位置：core/pm_engine/dispatch/queue.py merge-back 失败分支。
- 分类判据：错误文本/退出码含「would be overwritten by merge」「working tree has modifications」「lock」→ 可重试；否则走既有 _should_enter_repair / 熔断路径。
- 可重试处置：spec 保持 implementing 或回 ready（保留 implementer_run 锚点与分支引用），不递增实现尝试预算（used count），等待卫检查通过后仅重试 merge；分支清理延迟到重试成功或放弃。

## D3 预算语义

- 实现尝试预算（agents.implement_attempts，缺省 6）只对「真正启动实现 run」计一次；merge-back 等待与合并重试不计。

## Non-Goals

- 不修改 WIP 重叠闸门的 stash/block 策略。
- 不改 repair lane / 熔断触发条件。
- 不引入新配置键（顺延窗口复用既有 recovery 周期）。
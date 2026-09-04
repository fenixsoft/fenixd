# Proposal: fix-merge-untracked-guard

## Why

Fenixd 的 merge-back 死锁已复现 **3 次**（2026-08-26 add-agent-llm-isolation、2026-08-26 add-admin-activity-view、2026-08-29 v2-vendor-amis-sdk），每次都以 merge_streak 熔断告终，需要 Administrator agent 人工按固定处置模式救回。根因是主树的 untracked 文件与 implementer 分支提交的同路径文件冲突，`git merge` 拒绝「untracked working tree files would be overwritten by merge」。

框架现有的 Layer 2 兜底 `WorktreeManager._backup_untracked_spec_files()`（core/worktree_manager.py:238）只扫描 `spec/changes/` 路径下的 untracked 文件，**不覆盖任意产物路径**。第三次复现（v2-vendor-amis-sdk）的冲突源正是产物目录 `core/dashboard/static/v2/` 的 5 个 SDK 文件，落在现有兜底盲区内。任何主树 untracked 文件只要与未来 spec 的产物路径重合就会再次触发熔断。

本 SPEC 将现有兜底泛化：merge 前按 implementer 分支实际引入的文件路径，检测并移开所有冲突的 untracked 文件（不限于 spec/changes/），自动化 Administrator 已执行 3 次的处置模式。

## What Changes

- `core/worktree_manager.py` 的 `_backup_untracked_spec_files()` 泛化为按分支路径集合检测：merge 前取 implementer 分支新增的文件路径，找出主树中这些路径上 untracked 的文件，全部移入 `.fenix/merge-backup/<ts>/` 备份后再执行 merge
- 备份策略保持现有语义：merge 成功删除备份，merge 失败移回原位（不丢数据）
- 新增一致性保护：merge 成功后，若被移开的主树副本与 merge 后 HEAD 中同路径文件字节级不一致，保留该备份并告警（防止有价值的主树改动被分支版本静默覆盖后丢失）
- 不新增任何配置项（行为内建，无开关）

## Capabilities

### merge-untracked-guard

merge-back 前的 untracked 冲突防护：自动检测 implementer 分支将引入的文件路径与主树 untracked 文件的交集，移开备份后再 merge，保证任何主树 untracked 污染不再导致 merge-back 熔断。

## Impact

- **受影响代码**：`core/worktree_manager.py`（`_backup_untracked_spec_files`、`merge_back_from_branch` 及其备份消费逻辑）；merge 入口唯一（`merge_back(wt_path)` 委托 `merge_back_from_branch`），无其它调用面
- **受影响能力**：仅框架自身的 merge-back 流程；对 spec 的功能语义零影响
- **非目标**：不处理 stash pop 冲突变体（另案）；不引入配置项或 Dashboard UI；不改动 `ensure_clean_tree` 的 autostash 行为

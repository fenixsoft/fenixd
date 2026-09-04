# merge-untracked-guard Specification

## ADDED Requirements

### Requirement: merge 前检测并移开分支路径上的 untracked 冲突文件

`WorktreeManager.merge_back_from_branch(branch)` 在执行 `git merge --no-ff` 前，SHALL 计算该分支相对 HEAD 新增的文件路径集合（`git diff --name-only --diff-filter=A HEAD...<branch>`），并检测主树中位于这些路径上的 untracked 文件（`git ls-files --others --exclude-standard` 与前述集合的交集），将交集内的全部文件移入 `.fenix/merge-backup/<epoch秒>/` 目录（保持仓库相对路径结构）。检测范围 SHALL NOT 限于 `spec/changes/`——任意产物路径（如 `core/dashboard/static/v2/`）均须覆盖。

#### Scenario: 主树 untracked 文件与分支新增路径重合时被移开

- **WHEN** 主树存在 untracked 文件 `core/dashboard/static/v2/sdk.js`，且 implementer 分支新增了同路径文件
- **THEN** merge 执行前该文件被移入 `.fenix/merge-backup/<ts>/core/dashboard/static/v2/sdk.js`，merge 不再报「untracked working tree files would be overwritten」且成功

#### Scenario: 主树 untracked 文件与分支路径无交集时不被移动

- **WHEN** 主树存在 untracked 文件 `notes/scratch.txt`，分支新增路径集合不包含它
- **THEN** 该文件留在原地不被移动，merge 正常执行

### Requirement: merge 失败时备份文件移回原位

当 `git merge` 失败时，系统 SHALL 在 `merge --abort` 后把本次备份的全部文件从 `.fenix/merge-backup/<ts>/` 移回主树原路径（保留相对路径结构），使主树回到 merge 前状态供下一轮重试，不丢失任何数据。

#### Scenario: merge 失败后主树恢复原状

- **WHEN** merge 因分支冲突失败，此前已移开 untracked 文件 `a/b.txt` 至备份
- **THEN** `merge --abort` 后 `a/b.txt` 被移回主树原路径，备份目录被清空移除，主树工作区与 merge 前一致

### Requirement: merge 成功后按字节一致性决定备份去留

merge 成功时，系统 SHALL 对备份中每个文件与 merge 后 HEAD 中同路径文件做字节级比对：一致的文件随备份目录一并删除；存在不一致文件的，SHALL 保留该备份目录不删除，并写入告警日志（说明哪些路径的主树副本与合入版本不一致、备份位置），防止主树上的有价值改动被分支版本静默覆盖后丢失。

#### Scenario: 备份副本与合入版本一致时清理备份

- **WHEN** merge 成功，且备份中被移开的文件与 HEAD 同路径文件内容完全一致（冗余污染，如三次复现案例）
- **THEN** 备份目录被删除，无残留

#### Scenario: 备份副本与合入版本不一致时保留备份并告警

- **WHEN** merge 成功，但备份中被移开的某文件与 HEAD 同路径文件内容不同
- **THEN** 该备份目录保留在 `.fenix/merge-backup/<ts>/`，日志出现包含不一致路径清单与备份位置的告警条目

### Requirement: 分支新增路径集合为空时零开销跳过

当分支相对 HEAD 无新增文件（`--diff-filter=A` 集合为空）时，系统 SHALL 直接执行 merge，不创建备份目录、不产生任何文件移动。

#### Scenario: 纯修改分支不触发备份

- **WHEN** implementer 分支只修改既有 tracked 文件、无新增文件，主树存在若干 untracked 文件
- **THEN** 不创建 `.fenix/merge-backup/` 新条目，merge 直接执行

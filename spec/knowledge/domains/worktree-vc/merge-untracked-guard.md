<!-- knowledge: capability=merge-untracked-guard rev=1 sources=spec/archive/2026-09-04-fix-merge-untracked-guard -->

# 未跟踪文件合并守卫

merge-back 前把主树上与分支新增路径重合的 untracked 文件移开备份，使 merge 不被「untracked working tree files would be overwritten」拒绝，且主树副本按字节一致性决定去留、不静默丢失。

## 现行规则

- merge 前移开冲突 untracked 文件：`WorktreeManager.merge_back_from_branch` 执行 `git merge --no-ff` 前，计算该分支相对 HEAD 新增的文件路径集合（`git diff --name-only --diff-filter=A HEAD...<branch>`），与主树 untracked 文件（`git ls-files --others --exclude-standard`）求交集，将交集内全部文件移入 `.fenix/merge-backup/<epoch秒>/`（保持仓库相对路径结构）。检测范围不限于 `spec/changes/`——任意产物路径（如 `core/dashboard/static/v2/`）均覆盖。
- 空集零开销跳过：分支相对 HEAD 无新增文件时直接执行 merge，不创建备份目录、不产生任何文件移动。
- merge 失败移回原位：merge 失败时在 `merge --abort` 后把本次备份的全部文件移回主树原路径（保留相对路径结构），备份目录清空移除，主树回到 merge 前状态供下一轮重试，不丢失任何数据。
- merge 成功按字节一致性定去留：对备份中每个文件与 merge 后 HEAD 同路径文件做字节级比对——一致的随备份目录一并删除；存在不一致文件的保留该备份目录不删除，并写入告警日志（说明哪些路径的主树副本与合入版本不一致、备份位置），防止主树上的有价值改动被分支版本静默覆盖后丢失。

## 溯源

- 史前复原（存量基线） — merge-back 对 untracked 冲突做防护；冲突文件与分支侧字节一致时豁免放行
- 2026-09-04 fix-merge-untracked-guard — 固化 merge 前交集移开备份、失败 abort 后移回原位、成功后按字节一致性定备份去留并告警、空集零开销跳过

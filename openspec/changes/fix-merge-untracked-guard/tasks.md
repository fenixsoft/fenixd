# Tasks: fix-merge-untracked-guard

## 1. 冲突检测与备份

- [x] 1.1 重构 `WorktreeManager._backup_untracked_spec_files`（core/worktree_manager.py:238）为接受 `branch` 参数：`git diff --name-only --diff-filter=A HEAD...<branch>` 取分支新增路径集合，对每条路径做「主树存在且 `git ls-files --error-unmatch` 失败」判断，仅将交集文件移入 `.fenix/merge-backup/<epoch秒>/`（保持相对路径）；集合为空时不创建备份目录直接返回 None（design D1/D2）
- [x] 1.2 更新 `merge_back_from_branch`（core/worktree_manager.py:848）调用点传入 `branch`，注释同步改为「按分支新增路径移开冲突 untracked」

## 2. 一致性保护

- [x] 2.1 修改 `_drop_backup`（core/worktree_manager.py:269）：删除前逐文件与 HEAD 同路径文件做字节级比对；全部一致删目录（现状语义），存在不一致则保留目录并以 `logger.warning` 记录不一致路径清单与备份位置（design D3）

## 3. 测试

- [x] 3.1 为主树 untracked 与分支新增同路径场景写测试：断言 merge 成功且文件被移入备份、merge 后工作区为分支版本（spec scenario 1）
- [x] 3.2 为无交集 untracked 场景写测试：断言非冲突 untracked 文件留在原地、不创建备份目录（spec scenario 2 + 4：纯修改分支零开销）
- [x] 3.3 为 merge 失败路径写测试：断言 `merge --abort` 后备份文件移回原路径、备份目录清空（spec scenario 3）
- [x] 3.4 为一致性保护写两个测试：字节级一致副本 → 备份目录被删；不一致副本 → 备份保留且 warning 日志含路径清单（spec scenario 5 + 6）

## 4. 验证收尾

- [x] 4.1 全量测试通过；用临时仓库手工复演 v2-vendor-amis-sdk 场景（主树 untracked SDK 文件 + 分支同路径）确认不再熔断
- [x] 4.2 确认无新增配置项、无 Dashboard UI 改动（proposal 非目标），更新 proposal/tasks 勾选后提交

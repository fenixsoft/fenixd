# Merge Tree Rehearsal — 合并预演与语义冲突直通修复

## Why

merge-back 冲突在「真合并已触主树」之后才暴露（guard 锁内 stash→merge→abort），主树短暂进入半合并态、伴随 autostash 收拢/弹出舞蹈，冲突分类信息在 abort 后才可得。调度层虽有 repair 通道（add-merge-back-repair-lane 已落地，implementer 与 fast-track 双路覆盖），但进入 repair 前主树已被扰动、且失败已计入 fp 熔断记账。实测代价（2026-09-04 task-track）：二轮 re-dispatch 多耗约 32 分钟，spec 全程 16.1M input tokens、$4.60。把语义冲突拦截在「主树零污染点」，conflict 直接转 repair，避免整轮扰动与记账污染。

## What Changes

- **merge-tree 预演闸**：`merge_back_from_branch` 真合并前先 `git merge-tree --write-tree` 只读预演；零冲突 → 现行真合并流程逐字节不变。
- **语义冲突零污染直通 repair**：预演检出语义冲突 → 不 stash、不 merge、不 abort（主树全程未触碰），结构化冲突信息直接返回调度层转 repair 通道；该路径不经 `_merge_fp`/`_merge_streak` 记账、不做 ready 降级，spec 保持 in-flight（轮次上限由 repair 通道既有 `_repair_round` 封顶兜底）。
- **产物冲突走现行自愈**：预演检出全部冲突为构建产物/ignored-DU → 照常执行现行真合并 + 产物自愈路径，行为不变。
- **git 版本探测回退**：`merge-tree --write-tree` 需 git ≥ 2.38；运行时一次性探测，不支持则整体回退现行行为（预演闸跳过）。

## Capabilities

### New Capabilities

- `merge-rehearsal`: merge-back 前置预演——语义冲突在主树零污染点被拦截并直通 repair 通道，产物冲突保持现行自愈真合并。

### Modified Capabilities

（无——`mergeback-inplace-repair`、`merge-circuit-breaker` 为未归档 change 的能力声明，本 SPEC 不改其 Requirement 语义：repair 通道判定条件、轮次上限、remerge 失败链的 fp 熔断全部保持；本 SPEC 仅把「进入 repair 前的主树扰动」消除并新增预演入口。）

## Impact

- **代码**：`core/worktree_manager.py`（merge_back_from_branch 预演闸 + git 探测）、`core/pm_engine/dispatch.py`（语义冲突直通 repair 路由、跳过 fp 记账分支）
- **测试**：`tests/test_merge_tree_rehearsal.py`（new）+ test_worktree_merge_guard.py / test_mergeback_repair_lane.py / 熔断相关回归

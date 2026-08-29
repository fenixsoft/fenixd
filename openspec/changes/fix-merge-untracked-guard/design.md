# Design: fix-merge-untracked-guard

## Context

merge-back 死锁已复现 3 次（add-agent-llm-isolation、add-admin-activity-view，2026-08-26；v2-vendor-amis-sdk，2026-08-29，fp=752b442281cf）。每次根因相同：主树 untracked 文件与 implementer 分支提交的同路径文件冲突，`git merge` 拒绝覆盖 untracked 文件，连败 2 次触发 merge_streak 熔断置 blocked，需 Administrator agent 按「备份/移除 untracked → 手动 merge → 复位状态」的人工模式救回。

现有防线（core/worktree_manager.py）：

- `ensure_spec_committed`（~L197）：派发前把 untracked 的 spec 目录提交进主树 —— 只护 spec 目录
- `_backup_untracked_spec_files`（L238-267）：merge 前把 `openspec/changes` 下 untracked 移入 `.fenix/merge-backup/<ts>/` —— **路径限定死 `openspec/changes`，产物路径盲区**（第三次复现的 `core/dashboard/static/v2/` 恰在盲区外）
- `merge_back_from_branch`（L821-882）：唯一真实 merge 入口（`merge_back(wt_path)` L884 委托至此）。成功 `_drop_backup`（L858）、失败 `merge --abort` + `_restore_backup`（L871-876）

Administrator 对 v2-vendor-amis-sdk 的处置已验证字节级比对的价值：5 个 untracked 副本与分支版本 IDENTICAL（冗余污染），据此安全移除。

## Goals / Non-Goals

- **Goal**：merge 前自动移开所有与分支新增路径冲突的 untracked 文件（不限 openspec/changes/），复用现有备份/恢复/清理语义，消灭此类熔断
- **Goal**：保留有价值主树改动——副本与合入版本不一致时不静默丢弃
- **Non-Goal**：不处理 stash pop 冲突变体（另案，见 memory fenix-stashpop-unmerged-deadlock）
- **Non-Goal**：不新增配置项、不加 Dashboard UI（行为内建无开关）
- **Non-Goal**：不改 `ensure_clean_tree` autostash 行为（stash 栈堆积是独立问题）

## Decisions

### D1: 按分支路径集合求交集，而非全仓库扫描

merge 前先 `git diff --name-only --diff-filter=A HEAD...<branch>` 取分支**新增**文件路径集合（untracked 冲突只会发生在新增路径上——修改既有 tracked 文件不会与 untracked 冲突），再对主树逐路径判断「存在且未被 index 跟踪」（`git ls-files --error-unmatch <path>` 失败即 untracked）。

- 备选：全仓库 `git ls-files --others` 再与分支集合求交。fenixd 仓库规模小两者皆可，但逐路径判断只对分支新增路径数（通常 <20）做存在性检查，无全仓库遍历，语义也更直白。
- `--diff-filter=A` 涵盖新增；rename 场景（R）目标路径也是新路径，极罕见且 merge 对 rename+untracked 的行为本就特殊，不在本 SPEC 处理范围。

### D2: 泛化 `_backup_untracked_spec_files(branch)`，保留原函数名或就近改名

签名从无参改为接受 `branch`，内部逻辑替换为 D1 的交集检测。原「openspec/changes 全量移开」行为被交集行为**取代**：非冲突的 untracked spec 文件留在原地（merge 不受非冲突 untracked 影响，副作用更小且符合 spec 的「无交集不移动」场景）。调用点 L848 无需变化（传参即可）。

### D3: 一致性保护放在 `_drop_backup` 内

`_drop_backup`（L269）删除前逐文件与 HEAD（此时已含合入内容）同路径文件字节比对（读文件 bytes 相等即可，无需 git 命令）：全部一致 → 删目录（现状）；存在不一致 → 保留目录 + `logger.warning` 列出不一致路径与备份位置。孤儿空父目录清理逻辑保持。无新配置项，行为内建。

### D4: 单元测试走真 git 仓库 fixture

现有 worktree_manager 测试若已有 tmp git repo fixture 则复用；否则用 `git init` 临时仓库构造：主树 untracked 文件 + 分支新增同路径 → 断言 merge 成功；构造内容不一致副本 → 断言备份保留 + warning。四个 spec scenario 各对应至少一个测试。

## Risks / Trade-offs

- **漏检 rename 目标路径**：概率极低，后果退化为现状（merge 失败 → `_restore_backup` 恢复 → 熔断路径与今天相同），不劣化
- **不一致副本保留后无人清理**：`.fenix/merge-backup/` 会积累告警备份；接受——告警日志已给出路径，人工决策价值高于自动丢弃；量级预期极低（三次复现均为 IDENTICAL）
- **`git diff HEAD...branch` 对未 fetch 分支失效**：分支为本地 worktree 分支，恒存在，无此风险

## Migration Plan

纯行为替换，无状态迁移。旧 `.fenix/merge-backup/` 目录语义兼容（时间戳命名不变）。上线即生效，无 feature flag。

## Open Questions

无。

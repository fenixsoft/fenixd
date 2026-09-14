## Context

2026-09-07 三次 merge-back stash pop 冲突（04:23Z HookManager.tsx / 08:49Z runner.py / 18:00Z test_worktree_reuse.py）暴露三个缺口：通知静默（spec.error 瞬态 + 单次 ERROR 够不着指纹风暴门槛，admin_alerts 零记录）、条目滞留（内容已被取代仍保留，75 条 fenix autostash 无限期堆积）、冲突无预警（WIP 与分支改动同文件是碰撞基质）。

冲突真实双方是「合并分支内容 vs 主树并行会话未提交 WIP」——分支在 `_main_tree_lock` 内串行合并，分支间语义冲突走 merge-tree 预演 → repair 通道，不会到达 stash pop。修复对象是 dispatch.py `_report_stash_pop_conflict`（上报点）、worktree_manager.py `restore_after_merge`（自愈点）与 `merge_back_from_branch`（预检点）。

## Goals / Non-Goals

- Goals：冲突事件在 admin_alerts 留痕并可处置；零独有内容的 stash 条目自动清理；冲突前给出重叠预警
- Non-Goals：不改 merge/预演闸/reclaim 巡检的执行顺序；不动 spec.error 字段既有行为；不做 stash 栈批量清理（遵循 autostash 勿批量删约定）；不引入新配置键

## Decisions

### D1 告警直发复用 admin_store.append 管道

`admin_store.append` 自动补 id/created/handled（admin_store.py:139），daemon 主循环已有直接 append 先例（fenixd.py:789），pm_engine 已 import admin_store（engine.py:1224）。在 `_report_stash_pop_conflict` 内追加写入，conflict_files 为空时早退（现状已如此）。新类型进 `STORED_SIGNAL_TYPES` 白名单否则 monitor 扫描跳过（admin_monitor.py:389），SIGNAL_SEVERITY=major、SIGNAL_RECOMMENDATION 给核对指引。前端仅 activities/index.tsx label 映射加一行；`signal_type` 在 TS 侧是宽松 string（dashboard.ts:86），无联合类型要改。

### D2 drop 判据用树级 diff + sha 钉住

pop 前先 `rev-parse stash@{0}` 钉住 sha（此时在 `_main_tree_lock` 内，栈顶即刚 push 的条目）；自愈后对每个 UU 文件跑 `git diff --quiet <sha> HEAD -- <file>`——stash 提交树即 stash 时刻工作区快照，HEAD 已含合并结果，退出码 0 即「stash 版被合并结果完全取代」。全部相同 → 复用 4f753ed 在 reclaim_stale_autostash（worktree_manager.py:1504-1538）的 drop 模式：先核对 sha 仍为栈顶再 drop，sha 记日志。任一不同 → 保留，告警给 `git show <sha>:<file>` 找回命令。二进制/模式变更由 `--quiet` 树级 diff 天然覆盖。

### D3 重叠预检在 stash 之前、预演闸之后

`merge_back_from_branch` 拿到分支名后、调 `ensure_clean_tree` 前：脏 tracked 文件清单从 `git status --porcelain` 提取（ensure_clean_tree 已有同款解析，提炼为 helper 复用），分支改动文件用 `git diff --name-only $(git merge-base HEAD <branch>) <branch>`，交集非空 → WARNING + 挂 `MergeConflictInfo.wip_overlap` 新字段。只读、不阻断；dispatch 把清单并入告警 description。无重叠时零行为变化。

## Risks / Trade-offs

- drop 是删除性操作：判据必须树级 diff 而非文本比较，且 sha 栈顶核对防并发插队；误判兜底 = sha 已记日志，gc 前可找回
- 告警量：冲突事件低频（历史 3 个月 5 次），无风暴风险；不加节流
- MergeConflictInfo 兼容 `(bool, str)` 解包（dispatch.py:804 既有先例），新增字段走属性附加，不破坏既有解包
- 前端改 src 不提交 dist（框架 merge 后自动重建），交付物声明只列 src 文件

## Migration Plan

无状态迁移、无配置新增。存量 75 条 stash 不批量清理，靠既有 reclaim 巡检按现状 drain。

## Open Questions

（无）

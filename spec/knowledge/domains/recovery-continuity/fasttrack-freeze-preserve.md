<!-- knowledge: capability=fasttrack-freeze-preserve rev=1 sources=spec/changes/fix-fasttrack-freeze-branch-preservation -->

# 快车道冻结即保全

fast-track 四处「重试耗尽/零变更哨」冻结转人工站点在 `freeze_for_human` **之前**对实现现场做保全（preserve-before-freeze），使冻结不再丢失实现分支——single-app 事故（13 个已验证提交险随无保护 `branch -D` 丢失）的修复防线 1；自动清理入口对冻结现场的删除守护为防线 2。解冻续做消费侧见 [快车道恢复续做](fasttrack-recovery-resume.md)。

## 现行规则

- **冻结即登记**：实现分支相对解析基线（`resolve_base_branch` 单源）存在未合并提交时，冻结前必须完成「pre-rmtree 快照（`_snapshot_dirty_worktree` 语义单源，clean 目录无产出属正常）+ `_frozen_hold: True` + `branch`/`implementer_run` 锚点回写」，三键同一原子写窗口（`update_spec` 单条目写），MUST NOT 拆两次写。
- **分支解析同源**：三层解析（STATE.branch → `find_worktree_by_spec` → `find_branches_by_spec`）与 `_resolve_preserved_branch` 同口径，MUST NOT 另持平行副本。
- **零提交退化**：rev-list 非空闸门先行——零未合并提交时不置 hold、不产快照、不写锚点（行为与无保全一致，R1 退化条款）。
- **fail-open**：保全 IO 故障降 ERROR 审计留痕后冻结链照常继续，冻结本身不可被保全故障阻断；保全主体不吞异常，由 `_freeze_preserve_note` 包装兜底。
- **告警证据含保全摘要**：保全摘要（branch/ahead/snapshot/hold）拼进四处站点 evidence → 人工升级告警可直接定位分支（R2）。
- **幂等**：entry 已有 `_frozen_hold` 且 `branch` 非空时跳过重复快照与重复写。
- **原子写形态**：不复用 `mark_frozen_hold`——其锁内复核要求 `frozen` 已置位（冻结终止场景 frozen 在前 hold 在后），保全发生在冻结之前复核必放弃；扩展其参数则须同放宽复核、违背其余调用点逐位不变。
- **清理守护（防线 2）**：凡能删 `fenix/<spec>-<ts>` 分支或 spec worktree 的自动清理入口，对 STATE 在册 `frozen=True 且 _frozen_hold: True` 的 spec MUST 跳过删除并 WARNING 留痕；守卫只认 STATE 在册条目，显式删除/归档收尾通道（先清 STATE 条目再清现场）天然不被反向阻断。

## 接线点与守护清单

- 助手：`core/pm_engine/dispatch/fast_track.py` `preserve_impl_site_before_freeze`（保全主体）+ `_freeze_preserve_note`（fail-open 包装 + evidence 摘要文本）；四处冻结站点（契约违反 `_reconcile_and_merge` / 硬校验失败 `_hard_check_fail_accounting` / 通用失败重试耗尽 `_handle_fast_track_failure` / 零变更哨 `_handle_fast_track_zero_change`）在 `freeze_for_human` 之前调用并拼 evidence。
- 守护清单（入口 × 守卫形态）：

| 清理入口 | 守卫 |
|---|---|
| `legacy_registry._reclaim_expired_legacy` → `_physically_reclaim_legacy`（调查定位的**实际删除者**：无保护 `branch -D`） | 出册（pop）**前**查守卫，命中跳过且记录保持在册——出册后跳过=记录永久丢失、目录失去豁免反被孤儿清扫拾取；STATE 整轮单次快照 |
| `stale_sweep.cleanup_stale_worktrees` 孤儿清扫 | 目录级守卫：整目录跳过（worktree remove 与分支处置一并保留），复用既有 `state_entries` 单次快照，零新增锁序 |
| `stale_sweep._gc_merged_branches` 守卫 (ii) / `lifecycle.cleanup` verifier 族 `_branch_protected_by_state` (c) 款 | 零代码改动——防线 1 置位 `_frozen_hold` 后既有三键守卫（blocked+frozen+hold）即生效 |

- 守卫正匹配口径：STATE 不可解析不触发豁免（不放宽删除行为基线）；分支删除侧另有 `_branch_protected_by_state` 不可解析→保守保留兜底，两口径不冲突。

## 溯源

- 2026-11-09 fix-fasttrack-freeze-branch-preservation（spec/changes/fix-fasttrack-freeze-branch-preservation） — 新增本能力：冻结前保全助手 + 四站点接线（hold/锚点/快照三键单写、零提交退化、fail-open、幂等、evidence 摘要）+ 清理入口冻结守护（legacy 回收出册前豁免、孤儿清扫目录级豁免）。动因实测：fast-track 冻结不写 `_frozen_hold` 使分支保护全失效，过期遗产回收链以无保护 `branch -D` 删除实现分支

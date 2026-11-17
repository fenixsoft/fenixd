# Findings：fast-track 冻结实现分支删除者调查（任务 1.1）

调查日期：2026-11-09。以 `core/pm_engine/dispatch/fast_track.py` 四处 `freeze_for_human`
站点（契约违反 / 硬校验失败 / 通用失败重试耗尽 / 零变更哨）为起点，穷举冻结后仍能删
`fenix/<spec>-<ts>` 实现分支或 spec worktree 的全部入口。

## 一、入口清单（冻结后仍能删实现分支 / spec worktree 的清理入口）

| # | 入口 | 触发时机 | 分支删除 | worktree 删除 | 冻结现场守卫现状 |
|---|---|---|---|---|---|
| 1 | `legacy_registry._reclaim_expired_legacy` → `_physically_reclaim_legacy`（core/worktree_manager/legacy_registry.py:717/:791） | daemon 启动路径（`cleanup_stale_worktrees` 开头） | **`branch -D`**（无保护检查） | remove --force + rmtree | **无任何守卫**——不查 `_branch_protected_by_state`（stale_sweep.py:835-840 注释已点名的既有缺口） |
| 2 | `stale_sweep.cleanup_stale_worktrees` 孤儿清扫（stale_sweep.py:302，分支删除段 :566-662） | daemon 启动路径 | `branch -D`（删前查 `_branch_protected_by_state`） | remove --force + rmtree | 分支侧 (c) 款要求 `blocked`+`frozen`+`_frozen_hold` 三键齐备——fast-track 冻结只写 `frozen` 不写 `_frozen_hold` → 保护失效；**目录侧无任何 frozen 豁免** |
| 3 | `stale_sweep._gc_merged_branches`（stale_sweep.py:56） | daemon 启动路径 | `branch -d`（仅已合并分支） | 不删目录 | 守卫 (ii)（:220-226）要求 `blocked`+`frozen`+`_frozen_hold`——`_frozen_hold` 缺失时失效；但 GC 只删 `--merged` 分支，未合并分支天然不删（n_unmerged 计数），`-d` 语义下已合并分支删除无内容损失 |
| 4 | `lifecycle.cleanup(wt, success=False)` verifier 族分支删除段（lifecycle.py:1015-1043） | run 失败收口（冻结前） | `branch -D`（删前查 `_branch_protected_by_state`，:1020） | remove + rmtree | `_frozen_hold` 置位后 (c) 款生效——本入口在冻结前运行，非「冻结后删除者」 |
| 5 | `lifecycle.cleanup_orphans`（lifecycle.py:1313） | daemon shutdown | 不删分支 | remove --force + rmtree（仅活动集内目录） | 保护集（interrupted_runs.json + STATE implementing 事实查询回落）不含 frozen（blocked）spec；但冻结发生在 run 收尾后，worktree 已被 `keep_for_reuse` 摘出活动集（legacy_registry.py:341），shutdown 时不在 `_active_worktrees` → 天然不触达 |

## 二、删除时序（single-app 事故形态复推）

1. fast-track run 失败/重派循环内，每轮 `_keep_fast_track_worktree`（fast_track.py:693）
   → `keep_for_reuse`（legacy_registry.py:230）→ `register_legacy` 登记
   `reuse=True` 遗产，`registered_at` 随每轮失败刷新。
2. 最后一轮重试耗尽 → 四站点之一 `freeze_for_human`（只写 `status=blocked` +
   `frozen=True` + error + 告警；**不写 `_frozen_hold`、不回写 `branch`/`implementer_run`
   锚点**）→ 本轮 `_keep_fast_track_worktree` 已在前置失败分支执行（最后一次
   `register_legacy` ≈ 冻结时刻）。
3. 冻结后 `frozen` 挡住一切派发，无新 run 认领 → 遗产宽限期
   `LEGACY_GRACE_SECONDS`（= `STALE_LOCK_IDLE_SECONDS` ≈ 120s，constants.py:23）
   过期。
4. daemon 重启（计划内重启 / 04:30 网络断供窗口杀 run 后 supervisor 拉起 / 人工
   重启）→ 启动清扫 `cleanup_stale_worktrees` → 入口 1：`_reclaim_expired_legacy`
   对已过期遗产执行 `_physically_reclaim_legacy`：
   snapshot（仅 dirty 时产出）→ `worktree remove --force` → prune → **`branch -D`**。
5. 结果：实现分支 ref 被删（未合并提交仅 reflog 窗口内可寻，`git gc` 后全丢）；
   `_frozen_hold` 缺失、STATE `branch` 为空 → `unfreeze_spec` →
   `_resolve_preserved_branch` 三层解析全空 → 从零重派。

## 三、为何未产快照

`_snapshot_dirty_worktree`（lifecycle.py:1168）只对 **dirty** worktree 产出快照
commit（`git status --porcelain` 非空才走 `git stash create`；clean 目录返回 `""`，
lifecycle.py:1208-1209）。single-app 的 13 个提交**已全部 commit**、worktree clean →
所有删除路径（入口 1/2/5 的快照点）都无快照产出；已提交成果随 `branch -D` 失去
ref。快照机制覆盖「未提交现场」，**不覆盖「已提交未合并」的分支 ref**——这正是
本 SPEC 防线 1 要补的洞：冻结时分支 ref 即保全锚点（`_frozen_hold` + `branch`
锚点），使入口 2/3 的既有 `_frozen_hold` 守卫生效、入口 1 新增守卫可判。

## 四、与 design 根因模型的差异

design 候选为「stale sweep 对冻结 spec 的孤儿分支处置 / lifecycle 分支删除段的
register_legacy 判定未覆盖 fast-track partial 形态 / 冻结后的收尾清理」。实测：

- **实际主嫌是入口 1（legacy 宽限期兜底回收链）**：`register_legacy` 判定本身工作
  正常（`keep_for_reuse` 走的正是它，分支被保留）；问题在**登记过期后的回收链
  （`_physically_reclaim_legacy` 的 `branch -D`）不豁免冻结现场**。
- 次嫌是入口 2（孤儿清扫）的目录删除无 frozen 豁免 + 分支保护因 `_frozen_hold`
  缺失失效——两处都在 daemon 启动路径一次性触发。
- 入口 3（分支 GC）因 `--merged` 预筛对未合并分支无害；入口 4/5 冻结后不触达。
- 「冻结后的收尾清理」不存在——冻结站点本身无清理动作，删除全部发生在**冻结之后
  的下一次 daemon 启动清扫**。

本 findings 已回写 design.md 根因模型段（任务 5.1 一并处理）。

## 五、接线点选择（支撑任务 2.1 / 3.1）

### 防线 1（R1 保全）

- 助手落点：`core/pm_engine/dispatch/fast_track.py`（FastTrackLane 方法）——四处
  站点同文件、evidence 拼装同处、`self._pm.state_machine` / `self._pm.agent_runner
  .worktree_manager` 就地可得，内聚最优。
- 原子写形态：设计给出两选一。选 **「助手单次 `.STATE.md.lock` 原子写」**（选项 B）：
  `mark_frozen_hold` 的锁内复核要求 `frozen` **已置位**（其为「冻结终止」场景设计，
  frozen 在前 hold 在后），而本保全发生在 `freeze_for_human` **之前**（frozen 尚未
  置位），复用会被复核放弃；扩展 `mark_frozen_hold` 加可选参数则须同时放宽复核
  条件，违背「其余调用点行为逐位不变」。故助手用 `update_spec` 单次写
  `{branch, implementer_run, _frozen_hold: True}`（update_spec 单条目写本身即
  flock 内读最新条目合并更新，满足「锁内以最新条目复核」口径）。
- 分支解析：三层（STATE.branch → `find_worktree_by_spec` → `find_branches_by_spec`）
  与 `_resolve_preserved_branch` 同源口径；基线经 `resolve_base_branch` 单源；
  rev-list 非空闸门先行，零提交退化不置 hold 不产快照（S4）。
- 快照：调 `worktree_manager._snapshot_dirty_worktree`（语义单源，外部调用先例：
  stale_sweep.py:503、legacy_registry.py:850 同包跨 mixin 调用）。
- 幂等：entry 已有 `_frozen_hold: True` 且 `branch` 非空 → 视为已保全登记，跳过
  重复快照与重复写。

### 防线 2（R3 守护）

按入口清单，代码改动两处 + 既有守卫生效确认两处：

1. **`legacy_registry._reclaim_expired_legacy`**：对过期遗产出册**前**查守卫——spec
   `frozen=True` 且 `_frozen_hold: True` → 跳过本条回收并 WARNING 留痕，记录保持
   在册（清扫豁免持续生效，下轮重启再查；人工解冻清 `_frozen_hold` 后自然放行）。
   守卫必须在出册前：出册后跳过会把记录永久丢失、目录失去豁免反被孤儿清扫拾取。
   STATE 不可解析时保守跳过（宁漏勿误，与 `_branch_protected_by_state` 同姿态）。
2. **`stale_sweep.cleanup_stale_worktrees` 孤儿清扫**：目录级守卫——spec
   `frozen=True` 且 `_frozen_hold: True` → 跳过整目录（含 worktree remove 与分支
   处置）并 WARNING 留痕。复用既有 `state_entries` 单次快照（:388），不新增锁序。
   该守卫覆盖 `keep_for_reuse` 登记未生效 / 遗产出册异常等「无遗产豁免」窗口。
3. **`_gc_merged_branches`**：既有守卫 (ii) 在 `_frozen_hold` 置位后即生效
   （`blocked`+`frozen`+`_frozen_hold` 豁免，stale_sweep.py:220-226），零代码改动。
4. **`lifecycle.cleanup` verifier 族 `branch -D`**：既有 `_branch_protected_by_state`
   (c) 款在 `_frozen_hold` + `branch` 锚点置位后即生效（lifecycle.py:1020），零代码改动。

显式 spec 删除/归档收尾通道（先清 STATE 条目再清现场）不在守卫对象内——守卫只认
STATE 在册的 `frozen+_frozen_hold`，STATE 条目已清即不命中，天然不反向阻断。

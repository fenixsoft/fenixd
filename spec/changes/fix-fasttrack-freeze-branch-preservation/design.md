# Design：fast-track 冻结实现分支现场保全

## 根因模型

single-app 事故的形态：run 收尾链路在「partial 申报 → 重派」循环中由 `_keep_fast_track_worktree`（`core/pm_engine/dispatch/fast_track.py:693`）保留 worktree；冻结转人工站点实测共四处（评审期补全：`fast_track.py:1076` 契约违反 / `:1308` 硬校验失败 / `:2165` 通用失败三类重试耗尽 + `:2300` 零变更哨三连；四处均无 mark_frozen_hold 伴调，同属事故损失形态——分支可携带早期尝试的未合并提交或 worktree 脏文件）调 `freeze_for_human`（`core/state_machine.py:2291`）——该单一入口只机械写 blocked/frozen/error/告警，**不触发任何保全**；随后保留的 worktree/分支被某条清理路径删除且未走 pre-rmtree snapshot（`core/worktree_manager/lifecycle.py:1283` 的快照未在此路径生效）。`mark_frozen_hold` 的既有调用面（fast_track.py:280、verification/pipeline.py:2948、repair_lane.py:665、queue.py:2744、spec_review.py:634）证明了「冻结即保全」已是框架惯例，fast-track 重试耗尽是漏网路径。

删除者的精确定位属实现期调查任务，结论见本目录 `findings.md`（以 findings 为准回写本段，2026-11-09 调查）：**实际主嫌是 legacy 宽限期兜底回收链**——失败重试循环内 `_keep_fast_track_worktree` → `keep_for_reuse` → `register_legacy`（`reuse=True`，`registered_at` 随每轮失败刷新）；冻结（无 `_frozen_hold`、无锚点）后 `frozen` 挡住一切派发、无新 run 认领，`LEGACY_GRACE_SECONDS`（≈120s）过期；下一次 daemon 启动清扫 `cleanup_stale_worktrees` → `_reclaim_expired_legacy` → `_physically_reclaim_legacy` 以**无保护 `branch -D`** 收尾（`stale_sweep._branch_protected_by_state` 注释已点名的既有缺口）。次嫌是孤儿清扫：目录侧无 frozen 豁免、分支侧 `_branch_protected_by_state` (c) 款因 `_frozen_hold` 缺失失效。其余候选均排除：分支 GC 因 `--merged` 预筛对未合并分支无害；lifecycle cleanup verifier 族与 shutdown 孤儿处置在冻结后不触达（worktree 已被 `keep_for_reuse` 摘出活动集）；冻结站点自身无清理动作——删除全部发生在冻结之后的下一次 daemon 启动清扫。「为何未产快照」：`_snapshot_dirty_worktree` 只对 dirty worktree 产出快照（clean 目录返回空），事故 13 个提交已全部 commit、worktree clean → 一切删除路径的快照点无产出，分支 ref 是唯一保全载体——防线 1 补的正是「冻结时分支 ref 即保全锚点」。修复不依赖单一候选成立——见下述分层防线。

## 方案：冻结即保全 + 清理守护（两道防线）

### 防线 1：冻结即保全（preserve-before-freeze）

新增共享助手（建议放 `core/pm_engine/dispatch/fast_track.py` 内部或 worktree_manager 层，实现期按内聚定位）：

```
preserve_impl_site_before_freeze(spec_name, worktree_or_none, base_hint=None) -> dict
```

职责（幂等、fail-open 但 MUST WARNING 留痕）：
1. 解析实现分支与 worktree（优先 `result.worktree_path` / STATE.branch / `find_branches_by_spec` 三层，与 `_resolve_preserved_branch` 同源口径，MUST NOT 另持平行副本）；
2. 相对解析基线（`resolve_base_branch`）rev-list 非空时：触发 worktree 清理端既有快照语义（`fenix: pre-rmtree snapshot <branch>`）并保留分支；
3. `mark_frozen_hold(spec_name, error=…)`（或等价原子写）置 `_frozen_hold: True` + 回写 STATE `branch`/`implementer_run` 锚点——锚点回写必须在 `.STATE.md.lock` 内以最新条目复核（与 unfreeze_spec 同一口径）。注意既有 `mark_frozen_hold` 的原子写只覆盖 `{_frozen_hold, _cancelled_hold, error}`（`core/state_machine.py:2456`），不含 branch/implementer_run——实现二选一：扩展 `mark_frozen_hold` 时新参数 MUST 可选缺省、其余五个既有调用点（fast_track.py:280、pipeline.py:2948、repair_lane.py:665、queue.py:2744、spec_review.py:634）行为逐位不变；或在助手内以单次 `.STATE.md.lock` 写覆盖全部字段。MUST NOT 拆成先后两次独立写（违背同一原子窗口）；
4. 返回保全摘要（分支/snapshot/ahead 数）供冻结 evidence 与告警文案引用。

四处冻结站点（≈:1076 / ≈:1308 / ≈:2165 / ≈:2300）在 `freeze_for_human` 调用**之前**调用助手，并把保全摘要并入 `evidence`（人工升级告警因此可带「分支已保全」结论）。`freeze_for_human` 本身不改契约；若实现期判定入口内聚更优（在 freeze_for_human 增可选保全回调），允许，但 MUST 保持其余调用点行为逐位不变。

零提交（rev-list 为空）时保全退化为记录性留痕（按 R1 退化条款 MUST 不置 `_frozen_hold`、不产快照），与 `_resolve_preserved_branch` 的零提交剔除口径一致。

### 防线 2：清理守护（sweep guard）

实现期定位到的实际删除者（以及所有能删 `fenix/<spec>-<ts>` 分支或 spec worktree 的入口：stale sweep、register_legacy 遗产处置、GC）统一增加守卫：读 STATE，spec 处于 `frozen=True` 且（`_frozen_hold: True` 或分支被保全登记）时 MUST 跳过删除并 WARNING 留痕。守卫读取走一次性 STATE 读取，MUST NOT 引入新锁序；与既有 `stale_sweep.py` 对 `find_branches_by_spec` 的使用共文件内聚。守卫只约束自动周期清理入口；显式 spec 删除/归档收尾通道（先清 STATE 条目、再清理现场）不属守卫对象，MUST NOT 被守卫反向阻断。

### 回归测试（tests/test_fasttrack_freeze_preservation.py，新建）

1. **事故复现**：构造 fast-track partial ×max_retries → 断言冻结后：分支存在且含实现提交、STATE `_frozen_hold: True`、`branch` 非空、存在 pre-rmtree snapshot 提交；worktree 可缺（载体三态交 resolve_resume_site 处置）。
2. **续做闭环**：对①的现场 `unfreeze_spec(status='implementing')` → 断言 `_recovery_resume: True`、branch/implementer_run 保留、`_frozen_hold` 清零。
3. **清理守护**：对①的现场分别驱动 stale sweep 与遗产清理入口 → 断言分支/worktree 不被删除且 WARNING 留痕。
4. **零提交退化**：分支无未合并提交时冻结不置 hold、不产快照、行为与现状一致。
5. **告警证据**：人工升级告警 evidence 含保全摘要（分支名/ ahead 数）。

## 兼容与风险

- preserve 失败（IO 异常）MUST NOT 阻断冻结本身（冻结优先：转人工通道不能因保全失败失效）——fail-open + ERROR 审计留痕，与 fast_track.py 既有 `freeze_for_human` IO 异常口径一致。
- 幂等：重复冻结/重复保全不产重复快照提交（快照前检测分支是否已有保全登记）。
- 告警文案变化（evidence 增保全摘要）属增量，消费方按文本展示，无解析契约。

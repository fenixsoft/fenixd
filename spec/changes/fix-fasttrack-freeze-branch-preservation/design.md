# Design：fast-track 冻结实现分支现场保全

## 根因模型

single-app 事故的形态：run 收尾链路在「partial 申报 → 重派」循环中由 `_keep_fast_track_worktree`（`core/pm_engine/dispatch/fast_track.py:693`）保留 worktree；重试耗尽时两处站点（`fast_track.py:1079` 契约违反 / `:2168` 最终失败）调 `freeze_for_human`（`core/state_machine.py:2291`）——该单一入口只机械写 blocked/frozen/error/告警，**不触发任何保全**；随后保留的 worktree/分支被某条清理路径删除且未走 pre-rmtree snapshot（`core/worktree_manager/lifecycle.py:1283` 的快照未在此路径生效）。`mark_frozen_hold` 的既有调用面（fast_track.py:280、verification/pipeline.py:2948、repair_lane.py:665、queue.py:2744、spec_review.py:634）证明了「冻结即保全」已是框架惯例，fast-track 重试耗尽是漏网路径。

删除者的精确定位属实现期调查任务（候选：stale sweep 对冻结 spec 的孤儿分支处置、lifecycle 分支删除段的 register_legacy 判定未覆盖 fast-track partial 形态、冻结后的收尾清理）；修复不依赖单一候选成立——见下述分层防线。

## 方案：冻结即保全 + 清理守护（两道防线）

### 防线 1：冻结即保全（preserve-before-freeze）

新增共享助手（建议放 `core/pm_engine/dispatch/fast_track.py` 内部或 worktree_manager 层，实现期按内聚定位）：

```
preserve_impl_site_before_freeze(spec_name, worktree_or_none, base_hint=None) -> dict
```

职责（幂等、fail-open 但 MUST WARNING 留痕）：
1. 解析实现分支与 worktree（优先 `result.worktree_path` / STATE.branch / `find_branches_by_spec` 三层，与 `_resolve_preserved_branch` 同源口径，MUST NOT 另持平行副本）；
2. 相对解析基线（`resolve_base_branch`）rev-list 非空时：触发 worktree 清理端既有快照语义（`fenix: pre-rmtree snapshot <branch>`）并保留分支；
3. `mark_frozen_hold(spec_name, error=…)`（或等价原子写）置 `_frozen_hold: True` + 回写 STATE `branch`/`implementer_run` 锚点——锚点回写必须在 `.STATE.md.lock` 内以最新条目复核（与 unfreeze_spec 同一口径）；
4. 返回保全摘要（分支/snapshot/ahead 数）供冻结 evidence 与告警文案引用。

两处重试耗尽站点在 `freeze_for_human` 调用**之前**调用助手，并把保全摘要并入 `evidence`（人工升级告警因此可带「分支已保全」结论）。`freeze_for_human` 本身不改契约；若实现期判定入口内聚更优（在 freeze_for_human 增可选保全回调），允许，但 MUST 保持其余调用点行为逐位不变。

零提交（rev-list 为空）时保全退化为记录性留痕（不置 `_frozen_hold` 亦可），与 `_resolve_preserved_branch` 的零提交剔除口径一致。

### 防线 2：清理守护（sweep guard）

实现期定位到的实际删除者（以及所有能删 `fenix/<spec>-<ts>` 分支或 spec worktree 的入口：stale sweep、register_legacy 遗产处置、GC）统一增加守卫：读 STATE，spec 处于 `frozen=True` 且（`_frozen_hold: True` 或分支被保全登记）时 MUST 跳过删除并 WARNING 留痕。守卫读取走一次性 STATE 读取，MUST NOT 引入新锁序；与既有 `stale_sweep.py` 对 `find_branches_by_spec` 的使用共文件内聚。

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

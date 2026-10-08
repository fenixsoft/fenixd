# 设计（add-codefix-mergeback-conflict-salvage）

## 现状

- 整批即弃点：core/code_fix.py:4436-4460（_run_batch_created，4050 行起）：ERROR「合回冲突，现场即弃（branch/tip_sha 入档案）」→ record_failed_batch(reason=merge_back_conflict, branch, tip_sha)（:4450；实现在 :583）→ _safe_cleanup(success=False)（:4455）→ 返回 consumed，无任何救回。
- WIP 分派：:4431-4435 wip_gate_blocked → _defer_merge_back（:3796），defer 零预算（.fenix/code-review/fix-deferred.json）。
- 失败档案：FIX_FAILED_REL=.fenix/code-review/fix-failed.json，字段 item_ids/fail_count/branch/tip_sha/detail_ref/failed_at/released；FAIL_RETRY_MAX=3（:84）；释放点 release_retryable_failed_batches（:904），新链启动调用 :2959。
- 隔离根因：批回归跑在 worktree（:4140，runner.run_regression project_root=wt；实现 core/regression.py:765），看不见 main 新提交；冲突在批末合回（core/worktree_manager/mergeback.py:157/171）经预演闸 _rehearse_merge_from_branch（:1074，git merge-tree --write-tree）才首次暴露。
- 现状无任何 rebase/cherry-pick 救回（core/ 全 grep 0 命中）。

## 方案决策

1. **救回插入点在即弃分支内、cleanup 之前**：检出真冲突后先走救回——resolve_base_branch（core/git_base_branch.py:66，已接入 6 处）解析当前基线 → 批分支 rebase → 重跑 runner.run_regression（:4140 同参）→ 通过则重走 wm.merge_back（mergeback.py:171）。任一步失败不重试（至多 1 次），失败降级走组粒度回收。救回重走合回若命中 wip_gate_blocked（WIP 预检在 merge_back 内部，与 :4431 同源），按既有 defer 路径零预算处理，不计救回失败、不触发组粒度回收。
2. **冲突文件集来源**：预演 MergeConflictInfo（core/worktree_manager/types.py）已携带冲突路径清单，cherry-pick 阶段以「提交是否触碰冲突文件」判定可回收性（本次实测 14 提交中仅 5ecc2281 触碰 core/state_machine.py，13/14 可组粒度回收）。
   - **承载与出账**：rebase 冲突先 abort 还原批分支，从当前基线新建承载分支逐组 cherry-pick；回收集重跑批回归（:4140 同参）通过后重走 merge_back 出账，二次回归仍不过则放弃回收、整批兜底入档案。
3. **cherry-pick 采用 commit（组）粒度**：commit-first 契约（agents/code-fix.md:34-39、108）允许逐组提交与收尾一次提交，本次批 14 commit 全同 message、item_id 批量列于 body——条目级精确归属不可靠，故按组回收；agents/code-fix.md 仅增强 body 的 item_id 结构化标注（如 items: 前缀清单），不强制一提交一条目。
   - **条目归属与兜底**：仍冲突提交的条目归属以提交 body 的 `items:` 清单解析为准（契约增强仅对新批生效）；旧契约批解析不出清单时保守兜底——无法归属到非冲突组的剩余未出账条目整体随兜底入失败档案（与现状整批入档同口径），不做无据归属。
4. **分支保真**：现场即弃后分支会被删（实测 fenix/code-review-fix-1790973716 已不存在、worktree 22:48:44 被 stale sweeper 回收，tip_sha 1db39735 仅 GC 前可用）——救回必须在 _safe_cleanup 前完成、单轮闭环，不得依赖分支跨轮存活。
5. **留痕**：救回各阶段 INFO（成功）/WARNING（失败降级）日志，最终结局单行汇总，便于同刻窗口按日志归因。

## 风险

- 救回二次回归与主树并发：复用 runner.run_regression 内部锁语义，避免与并行 evo 合回争锁死等（复用既有锁语义、不新增锁，实现期并发窗口验证一次）。
- rebase 改写批分支历史：分支为独立 worktree 分支且尚未合回，改写安全；cherry-pick 中间态复用既有 _safe_cleanup 收尾。
- GC 时效：方案不依赖 tip_sha 对象跨轮存活，救团单轮闭环规避。
- 契约增强（agents/code-fix.md）为行为约定变更，需核对 prompt_builder 引用处，无代码接口变化。
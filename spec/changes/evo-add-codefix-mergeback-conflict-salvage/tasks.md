## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: core/worktree_manager/mergeback.py
  kind: modify
- path: agents/code-fix.md
  kind: modify
- path: core/git_base_branch.py
  kind: reference
- path: tests/test_code_fix.py
  kind: modify
- path: tests/test_code_fix_mergeback_conflict_salvage.py
  kind: new
```

## 1. 合回冲突定向救回（rebase 一次）

- [ ] 1.1 core/code_fix.py：在 _run_batch_created 真冲突分支（:4436-4460）的 record_failed_batch 与 _safe_cleanup 之前插入定向救回：用 resolve_base_branch（core/git_base_branch.py:66）解析当前基线，对批分支执行一次 rebase，重跑批回归（:4140 runner.run_regression 同参），通过则重走 merge_back（core/worktree_manager/mergeback.py:171 merge_back_from_branch）；救回至多 1 次。
- [ ] 1.2 core/worktree_manager/mergeback.py：为救回路径暴露冲突文件集查询（复用 _rehearse_merge_from_branch（:1074）的 git merge-tree 预演与 MergeConflictInfo 冲突路径清单，core/worktree_manager/types.py），供 cherry-pick 阶段判定提交可回收性。
- [ ] 1.3 core/code_fix.py：保证救回发生在 _safe_cleanup（:4455）之前、批分支引用全程可用；救回失败时仍走整批入失败档案兜底（行为与现状兼容）；wip_gate_blocked defer 零预算路径（:4431-4435）不触发救回；救回重走合回命中 wip_gate_blocked 时同样按 defer 零预算处理，不计救回失败。

## 2. 冲突组粒度回收与契约增强

- [ ] 2.1 core/code_fix.py：rebase 冲突时先 abort 还原批分支，从当前基线新建承载分支按 commit 粒度 cherry-pick 回收不触碰冲突文件的提交；回收集重跑批回归（:4140 同参）通过后重走 merge_back，对应条目按 resolved 出账；仍冲突提交对应条目入 record_failed_batch 计 fail_count（沿用既有预算语义）——归属以提交 body 的 items: 清单解析为准，旧契约批解析失败时剩余未出账条目保守整批入档案（同现状兜底口径）。
- [ ] 2.2 agents/code-fix.md：commit 契约补 body 的 item_id 结构化标注（如 items: 前缀清单），使条目归属可从 commit 组粒度反查；保留逐组提交与收尾一次提交的既有弹性（:34-39、:108）。
- [ ] 2.3 core/code_fix.py：救回各阶段（rebase/二次回归/cherry-pick/最终结局）落 INFO/WARNING 日志，最终结局（整批救回/部分回收/兜底全弃）单行汇总。

## 3. 测试

- [ ] 3.1 tests/test_code_fix_mergeback_conflict_salvage.py（新建）：覆盖真冲突→rebase 成功救回（不整批入档案）、rebase 仍冲突→非冲突组 cherry-pick 回收、冲突组条目入档案计 fail_count、救回发生在 cleanup 前分支可用、defer 路径不触发救回、回收集二次回归仍不过→放弃回收整批兜底、旧契约批无 items: 清单→保守整批兜底。
- [ ] 3.2 tests/test_code_fix.py：补回归——wip_gate_blocked defer 路径行为不变；救回失败兜底整批入档案与现状一致；救回各阶段日志留痕断言。
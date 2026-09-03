## Deliverables

```yaml
- path: core/worktree_manager.py
  kind: modify
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/pm_engine/budget.py
  kind: modify
- path: tests/test_mergeback_repair_lane.py
  kind: new
```

## 1. git 层：冲突分类与换壳支持

- [x] 1.1 worktree_manager merge-back 失败返回值附带结构化冲突分类（冲突路径清单、产物自愈是否适用、是否仍有语义冲突），保持既有 (bool, str) 兼容
- [x] 1.2 worktree_manager 支持在既有分支上创建 worktree（checkout 而非 -b 新建），并暴露按分支解析 worktree 存在性的查询（以 git worktree list 为准，不信任内存表）

## 2. repair agent 派发管线

- [x] 2.1 prompt_builder 新增 repair prompt 模板：spec 身份 + 冲突清单摘要 + 方向说明（合 main 入分支、解冲突、跑测试、commit）+ 显式失败出口；不含原 worktree 地址类间接情报
- [x] 2.2 agent_runner 支持 repair run：run_id 前缀 `repair-<spec>-<ts>`，token 记所属 spec 名下，runs 记录带 repair 可辨识标识
- [x] 2.3 认领现场走 `_legacy` take 摘出 + `_spec_locks` 注册，确保 sweeper 宽限期不回收 repair 在用现场

## 3. 调度层 repair 决策

- [x] 3.1 dispatch 层 merge-back 失败处理分支：语义冲突时进入 repair 决策（产物自愈适用时不触发）；实现分支载体三态（原地/换壳/fallback）
- [x] 3.2 失败链轮次控制：`_repair_round` 计数、`MAX_REPAIR_ROUNDS_PER_FAILURE = 2` 模块常量（不新增配置键）、超轮次回退 fallback 重派
- [x] 3.3 fallback 重派 prompt 注入当次 merge 失败上下文；repair agent 显式失败/超时/预算耗尽同样回退 fallback
- [x] 3.4 熔断协同：repair 轮不清零 `_merge_fp`/`_merge_streak`；re-merge-back 再失败连续累计；blocked 状态拦截 repair 派发
- [x] 3.5 主树干净态保证：派 repair 前校验主树无半合并残留（abort 完成性）；repair 完成后走既有 merge_back_from_branch 重推

## 4. 测试与回归

- [x] 4.1 tests/test_mergeback_repair_lane.py：覆盖 specs 全部 Scenario（语义冲突触发/产物自愈不触发、三态、sweeper 竞态、prompt 形态、预算归账、轮次超限、熔断协同、主树干净态）
- [x] 4.2 既有套件回归：test_worktree_merge_guard.py、熔断相关测试、派发测试全绿（自愈与重派既有路径零行为差异）

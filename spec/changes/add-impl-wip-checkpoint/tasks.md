## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/worktree_manager.py
  kind: modify
- path: tests/test_impl_wip_checkpoint.py
  kind: new
```

## 1. 锚点 A：排水超时收口 WIP 提交

- [ ] 1.1 shutdown 序列新增静默窗口提交步骤：`wait_for_running_agents()` 完成后、`cleanup_orphans(protected)` 之前，对 preserved_wts 中每个已注册 worktree 执行 WIP 提交（空变更 `git status --porcelain` 为空则跳过；git 操作 15s 超时；失败 WARNING 留痕不阻塞收口）
- [ ] 1.2 WIP 提交 helper 与消息契约：`fenix(wip): checkpoint drain-preserve <spec>` 前缀格式，`git add -A` 尊重 gitignore；helper 供锚点 A/B 复用
- [ ] 1.3 单测（tests/test_impl_wip_checkpoint.py）：排水超时场景中断后分支 ahead≥1；下一 daemon `_recovery_preserve_spec` 判定走保留分支续做；空变更不产生空提交；git 超时降级收口继续

## 2. 锚点 B：transient 原地退避前 WIP 提交

- [ ] 2.1 attempt 循环瞬断路径插入：`transient_retry` 记录写入后、`time.sleep(backoff)` 前对当前 attempt 的 worktree 执行 WIP 提交（复用 1.2 helper，anchor=`transient-backoff`）；无 worktree 载体时跳过，现行行为逐字节不变
- [ ] 2.2 单测：退避窗口内 daemon 死亡后分支 ahead≥1 且 recovery 走保留续做；后续 attempt 以 `--resume` 续跑不受 WIP 提交影响；无 worktree 场景跳过

## 3. merge-back 前塌缩

- [ ] 3.1 塌缩实现（worktree_manager 成功收口 choke point）：merge_back 前识别分支上全部 `fenix(wip):` 前缀提交，`git reset --soft <merge-base>` 后以最终提交消息重建成单提交；无 WIP 提交时零动作
- [ ] 3.2 单测：`base→wip→wip→final` 塌缩后 merge-back 所见为单提交（消息取自 final）、主树历史无 wip 前缀、文件内容逐字节不变；仅 WIP 无最终提交（恢复续做后收口）场景；无 WIP 常规路径零动作；塌缩重入幂等

## 4. 回归与收尾

- [ ] 4.1 recovery 集成回归：`_recovery_preserve_spec` 命中路径全链（interrupt-recovery-preserve 既有用例 + 新增 WIP 前置条件命中变体）；瞬断重试既有用例（fix-provider-transient-backoff）回归
- [ ] 4.2 全量回归 `python3 -m pytest tests/ -q` 通过（对照既有 10 个环境性失败基线：block_main_tree_write hook / planner_scenarios_batching hook / dashboard dist 类）

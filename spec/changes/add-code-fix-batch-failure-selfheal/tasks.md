## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix.py
  kind: modify
```

## 1. 批收尾三态与链自驱动

- [ ] 1.1 `_run_batch_inner` / `_run_batch_created` 返回值从 bool 改为三态字符串 `"success"` / `"consumed"` / `"halt"`，按 design D1 映射六条 consumed 失败路径与三条 halt 路径；`_run_batch` 对 `success`/`consumed` 执行 `_resubmit()`、仅 `halt` 终止链，同步改写「失败批不再自驱动」既有注释（收敛性论证：consumed 批条目已离开可选池，循环必然终止）
- [ ] 1.2 「两次回归均失败」与「合回冲突」两条路径改为现场即弃：cleanup 前以 `_worktree_head` 取 `tip_sha` 并连同 `branch`、`reason` 写入失败档案，随后 `_safe_cleanup` 清理 worktree 并释放 `code-review-fix:code-fix` 锁；进度 `current` 改为「第 N 批失败已跳过（原因）— 继续后续批次」，`phase` 用非终态值（design D6），不再走 `_finish("failed")`
- [ ] 1.3 `agent_run_failed`、`regression_retry_run_failed` 与 `no_effective_fix`（零有效修复拒合回，core/code_fix.py 既有 `_finish("failed", reason="no_effective_fix")` 分支）路径：条目写入进度快照 `chain_skipped` 字段（原子写合并语义），保持 `_safe_cleanup`，收尾返回 `consumed`（不再走 `_finish`，进度文案按 1.2 同款非终态）
- [ ] 1.4 `FIX_PROGRESS_DEFAULT` 新增 `"chain_skipped": []`；`select_batch` 新增可选参数 `exclude_ids`（排除口径 = 失败档案并集 ∪ exclude_ids，缺省 None 向后兼容）；checkpoint 选批处传入 `chain_skipped`；新链启动（非同一 activation_id）处显式重置 `chain_skipped` 为空列表；checkpoint「选批为空」分支（既有 `reason=failed_batch_retained`）文案按 design D5 注记改写（区分 chain_skipped/预算内档案与达上限档案，consumed 链的正常收敛出口不得误报为故障）

## 2. 失败档案重试预算

- [ ] 2.1 `record_failed_batch` 记录新增 `fail_count`（首记 1）/`reason`/`branch`/`tip_sha`/`failed_at` 字段；同 item_id 集合再次入档时复用既有记录 `fail_count` 递增并刷新其余字段，不追加重复记录；`fail_count` 递增至 `FAIL_RETRY_MAX` 的那次写入一条 warning 告警（复用既有告警通道，列明条目集与原因），此后不再发；`record_failed_batch` 以可选关键字参数扩展签名（`reason`/`branch`/`tip_sha`，缺省空串），既有调用点零破坏；`_append_todo_entry` 登记时机改为「达 `FAIL_RETRY_MAX` 那次入档」，文案移除「保留 worktree」「车道不再自动重派」表述、改按 `branch`/`tip_sha` 追溯
- [ ] 2.2 新增 `release_retryable_failed_batches(project_root)`：释放 `fail_count < FAIL_RETRY_MAX` 的档案记录（条目回到可选池），返回释放记录数；在新链启动处调用并记日志
- [ ] 2.3 模块常量 `FAIL_RETRY_MAX = 3`（不新增配置键）；模块 docstring 与 `fix-failed.json` 相关注释同步更新为「自动重试预算」语义（移除「防重复派发/待人工清理」的永久跳过表述）
- [ ] 2.4 `write_regression_failed_alert`（core/code_fix.py）告警措辞按 What-Changes「可见性去人工化」改写：description 移除「worktree 保留待人工排查」，recommended_action 改为「已跳过，下轮自动重试（达重试上限后需人工介入）」，evidence 的 worktree 路径改为 `branch`/`tip_sha` 追溯线索

## 3. 测试

- [ ] 3.1 三态收尾与自驱动用例：批成功与 consumed 失败（合回冲突、两次回归失败、零有效修复）均触发 `_resubmit`；worktree_create_failed / 批 worker 异常保持终止链不重投
- [ ] 3.2 锁释放用例：合回冲突与两次回归失败收尾后 worktree 目录被清理，同链下一批 `wm.create` 不再被既有锁拒绝（可用 create 返回非 None 或锁集合断言）
- [ ] 3.3 重试预算用例：首记 fail_count=1；同条目集再入档递增不重复；新链启动释放 fail_count<3 且保留 ≥3；递增达 3 时告警恰好一条且后续链启动不再发；todo.md 待人工项仅在 fail_count 递增至 FAIL_RETRY_MAX 的那次入档产生（预算内入档不产生）
- [ ] 3.4 chain_skipped 生命周期用例：agent run 失败与 no_effective_fix 条目进入 chain_skipped 且本链 select_batch 不再选中、不写入 fix-failed.json；新链启动后重置为空、条目重新可选
- [ ] 3.5 改写存量断言：原「保留 worktree（MUST NOT cleanup）」「失败批终止链（条目保持 open）」相关用例按新语义改写为「现场即弃 + 链继续」；`python3 -m pytest tests/test_code_fix.py -q` 全绿

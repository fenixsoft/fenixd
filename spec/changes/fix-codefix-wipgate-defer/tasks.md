## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: tests/test_code_fix.py
  kind: modify
```

## 1. 合回阻断分类与 defer 台账（D1/D2/D7）

- [ ] 1.1 批 worker 收尾合回失败分支首行读 `wip_gate_blocked`（`getattr(merge_info, "wip_gate_blocked", False)`）分派：True 走新 defer 路径（不 `_safe_cleanup`、不 `record_failed_batch`、进度 reason=`wip_gate_blocked`、current 含「主树未提交改动」与交集文件名）；False 分支保持既有「现场即弃」代码逐字不动
- [ ] 1.2 新增 `.fenix/code-review/fix-deferred.json` 原子读写原语（load/save + 同目录 `.lock` 惯例，对齐 `record_failed_batch` 风格）；条目字段 `worktree/branch/tip_sha/item_ids/defer_count/first_deferred_at/last_overlap`；defer 路径写条目（`first_deferred_at` 为 UTC ISO8601，`last_overlap` 取 `merge_info.wip_overlap`）
- [ ] 1.3 首次进入 defer 路径发一条 info 级 admin 告警，正文含 `last_overlap` 文件清单与「提交（git add/commit）或 stash（git stash push）主树改动」处置提示（文案复用 mergeback.py 升级出口话术）

## 2. 链边界自动重试（D4）

- [ ] 2.1 新增 `_process_deferred_merges()`：遍历台账逐条对保留 worktree 直接重跑 `wm.merge_back`；成功 → `mark_resolved` 核销 fixed 条目 + `_safe_cleanup(success=True)` + 移出台账 + 进度 done 累加（current=「延迟批合回成功（核销 N 条）」）；仍 `wip_gate_blocked` → 台账原样保留；其他异常 → try/except 记 warning 后继续下一条（不炸链节拍）
- [ ] 2.2 接线两个重试时机：checkpoint 内选批之前、`count_open_items==0` 收敛早退之前；两处都在既有锁内调用
- [ ] 2.3 `defer_count` 递增语义：仅当本次发生了实际 merge_back 尝试且仍被阻断时 +1；纯未到达重试点不递增；超时判定用 `first_deferred_at` 不受重试影响

## 3. 预算降级与人工升级（D6）

- [ ] 3.1 预算双门判定（`first_deferred_at` 超 90 分钟或 `defer_count` 达 6，先到为准）：`record_failed_batch(reason="wip_gate_blocked_expired", branch=, tip_sha=)` + `_safe_cleanup(success=False)` + 移出台账 + 批次文案「延迟批合回超预算已入失败档案」
- [ ] 3.2 降级时发一次性 admin 告警：同条目集（item_ids 指纹）只发一次，含交集文件清单与人工处置提示

## 4. 换链/重启再认领（D5）

- [ ] 4.1 新链启动（链身份判定处、`release_retryable_failed_batches` 旁）扫台账再认领：worktree 目录存在且 `tip_sha` 在分支可解析 → 原样保留（`defer_count`/`first_deferred_at` 不重置）；目录缺失或不可解析 → 移出台账 + warning 日志（条目未核销仍在 open 池，无需回写）

## 5. 测试（tests/test_code_fix.py）

- [ ] 5.1 分类单测：伪 `merge_back` 分别返回 `wip_gate_blocked=True/False` 的 `MergeConflictInfo`，断言 True 不写 fix-failed、不 cleanup、reason=wip_gate_blocked；False 走既有档案路径（fail_count 递增）
- [ ] 5.2 defer 端到端单测：首合回被阻断→台账七字段齐全且 worktree 保留；主树变干净后链边界重试→条目核销、台账清空、进度 done 累加
- [ ] 5.3 预算单测：注入过期 `first_deferred_at` / 打满 `defer_count` → 降级入档案（reason=wip_gate_blocked_expired）+ worktree 清理 + 告警一次性（同指纹二次降级不再发）
- [ ] 5.4 再认领单测：台账含存活与丢失两条 → 存活保留字段不变、丢失移除并记 warning
- [ ] 5.5 回归锁定：真冲突路径行为与改动前一致（档案 reason=merge_back_conflict、fail_count、cleanup、链继续）

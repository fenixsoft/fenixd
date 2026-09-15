## Deliverables

```yaml
- path: core/pm_engine/dispatch.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: core/worktree_manager.py
  kind: modify
- path: tests/test_repair_commit_enforcement.py
  kind: new
```

## 1. repair git 事实复核（A）

- [ ] 1.1 在 `core/worktree_manager.py` 新增只读查询辅助：`branch_tip(branch)`（返回分支 tip SHA）与 `repair_site_facts(wt_path)`（返回 `{unmerged: [...], merge_head: bool}`，基于 `git ls-files -u` 与 `git rev-parse -q --verify MERGE_HEAD`），异常时以保守值降级不抛穿
- [ ] 1.2 在 `_dispatch_repair_lane` 派发前记录基准 tip：把 `_repair_base_tip`（= `branch_tip(branch)`）与既有 `_repair_round`/`_repair_merge_fp` 同处一次 `update_spec` 落盘
- [ ] 1.3 在 `core/pm_engine/dispatch.py` 的 `_run_repair_worker` 中，`repair_ok` 判定之后、`_reconcile_impl_budget` 之前插入 git 事实复核：任一不满足（tip 未前进 / 有未合并条目 / 有 MERGE_HEAD）即置 `repair_ok=False` 并写入具体 `repair_error`
- [ ] 1.4 复核通过路径：re-merge 成功时清零 `_repair_base_tip`（并入既有 `_repair_round` 清零的 `update_spec`）
- [ ] 1.5 基准 tip 缺失或查询异常时，复核降级为「仅查冲突残留 + MERGE_HEAD」保守放行，不新增假阴性硬门

## 2. 回退上下文注入具体事实（A 收口）

- [ ] 2.1 `git 事实复核未通过` 的 `repair_error` 携带可诊断文本（base/now SHA、未合并条目计数、MERGE_HEAD 有无），并作为 `merge_error` 一并传入 `_fallback_after_repair`

## 3. repair prompt 契约强化（B）

- [ ] 3.1 重排 `_build_repair_prompt` 的「修复方向」步骤：开场清理残留 merge → merge main → 解决冲突 → **commit（强制终点）** → 定向回归测试
- [ ] 3.2 把「运行项目测试」替换为「本次合并触及文件的定向回归 + 有界超时」（示例给出 `timeout 600 python3 -m pytest <touched> -q`），明确不把全量套件作为提交前置
- [ ] 3.3 在 prompt 结论文本要求中写明：测试无法在窗口内跑完时 MUST 提交已解决的合并并标注未跑完的验证边界，禁止因测试未完而不提交

## 4. repair 开场清理残留 merge（C）

- [ ] 4.1 在 `_build_repair_prompt` 增加开场第一步：检测 worktree 是否残留 `MERGE_HEAD`，若有则先 `git merge --abort` 复位到干净 tip 再重新合入 main

## 5. 测试与回归（A/B/C 验证）

- [ ] 5.1 新增 `tests/test_repair_commit_enforcement.py`：四态覆盖——分支 tip 未前进 → 判未完成并回退；有未合并条目 → 判未完成；有 MERGE_HEAD → 判未完成；真提交 → 放行 re-merge-back
- [ ] 5.2 prompt 契约断言：`_build_repair_prompt` 输出包含「先提交后测试」顺序与「定向回归/有界超时」措辞，且含开场清理残留 merge 步骤
- [ ] 5.3 回退上下文断言：因 tip 未前进回退时，注入的 merge 失败上下文含「未提交/分支 tip 未前进」具体事实而非笼统原因
- [ ] 5.4 定向回归：`tests/test_mergeback_repair_lane.py`、`tests/test_repair_redispatch.py`、`tests/test_repair_remerge_pending.py`、`tests/test_merge_tree_rehearsal.py` 全绿（既有 happy path 逐字节不变）

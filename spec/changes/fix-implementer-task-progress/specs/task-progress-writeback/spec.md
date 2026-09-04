## ADDED Requirements

### Requirement: 回写三级兜底

`_sync_task_progress` 的 done_ids 为空处理从「直接跳过」改为三级回退：
1. `done_ids` 非空 → 精确对齐（既有行为不变）；
2. `done_ids` 空但 `flat_done` 非空且弱一致性校验通过（`created_count >= tasks.md 未完成项数的一半`）→ 按创建序勾选 tasks.md 扁平任务序列前 `max(flat_done)+1` 个未完成项；
3. 两者皆空 → 跳过（不误写）。

#### Scenario: 无编号 run 兜底回写
- **WHEN** 某实现 run 完成，subject 均无 tasks.md 编号（done_ids 空）但 flat_done={0,1,2,3}，tasks.md 有 27 项未完成且 created_count=6
- **THEN** `_sync_task_progress` 将 tasks.md 前 4 项未完成勾选为 `- [x]`（非 0），弱校验通过

#### Scenario: 弱校验不符跳过
- **WHEN** done_ids 空、flat_done 非空，但 created_count 远小于 tasks.md 未完成项数（如 created 2 / tasks 27）
- **THEN** 不执行回写，保持跳过且不产生任何 tasks.md 修改

#### Scenario: 精确路径不变
- **WHEN** done_ids 非空（subject 编号合规）
- **THEN** 仅按 done_ids 精确勾选，flat_done 不参与（既有行为无回归）
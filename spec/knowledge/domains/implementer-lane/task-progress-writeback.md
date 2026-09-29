<!-- knowledge: capability=task-progress-writeback rev=1 sources=spec/archive/2026-09-09-fix-implementer-task-progress -->

# 任务进度回写兜底

写侧回写（见 [task-progress-sync](task-progress-sync.md)）在 run 记录缺少任务编号时的三级兜底——done_ids 精确对齐优先，缺失时按创建序完成下标回退，两者皆空不误写。

## 现行规则

- 三级兜底按序判定：
  1. `done_ids` 非空 → 按 subject 内嵌的 tasks.md 任务编号精确勾选对应任务，`flat_done` 不参与（精确对齐路径无回归）。
  2. `done_ids` 为空、`flat_done` 非空且弱一致性校验通过（`created_count` ≥ tasks.md 未完成项数的一半）→ 按创建序勾选 tasks.md 扁平任务序列前 `max(flat_done)+1` 个未完成项。
  3. 两者皆空 → 跳过，不做任何 tasks.md 修改（不误写）。
- 弱一致性校验不通过（如 created_count 远小于 tasks.md 未完成项数）时不执行回写，保持跳过，不产生任何 tasks.md 修改。
- 兜底与精确路径同契约：回写只增不减、已勾选跳过。

## 溯源

- [2026-09-09 2026-09-09-fix-implementer-task-progress](spec/archive/2026-09-09-fix-implementer-task-progress/) — done_ids 为空时不再直接跳过：新增 flat_done（harness 创建序完成下标）回退勾选并配弱一致性校验防误写；done_ids 精确对齐路径保持不变

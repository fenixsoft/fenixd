# add-code-fix-item-level-progress 任务

## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: core/dashboard/data/code_review.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/CodeFixProgressCard.tsx
  kind: modify
- path: tests/test_code_fix_item_level_progress.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. D5 实证：out 产物落盘时序

- [ ] 1.1 以最小夹具批（1-2 条 item）驱动 `run_code_fix`（或直接以既有单测夹具复用其执行函数），在 agent run 期间与收尾后分别检查 `<worktree>/.fenix/code-review/fix-out-<run_id>.jsonl` 的存在性与行数，实证「逐条追加」契约的实际时序；实证结论以注释形式落在读侧合成函数头（含观察方法），并据此确认 1.2/2.x 的路径假设；若实证发现 agent 不逐条追加（收尾才一次性落盘），在读侧函数头记录实证结论并以「批内明细不可得→null」兜底路径为准，不修改 agent prompt

## 2. 写侧：批上下文落盘

- [ ] 2.1 `core/code_fix.py`：把 `phase="fixing"` 写点整体后移至建树成功之后（`wm.create()` 返回非 None、`run_code_fix` 调用之前），同次原子写入 `worktree`（本批 worktree 绝对路径）、`run_id`、`batch_total`（=len(items)）三键；`run_id` 由编排器**预生成**（保持 `code-fix-` 前缀、按 `_unique_code_fix_run_id` 同口径去重）并经 `run_code_fix` 既有 `run_id` 形参传入（maintenance_runs.py:1250），保证 run 在飞期间进度文件已可解析；新键 MUST 进 `FIX_PROGRESS_DEFAULT`（缺省 null，白名单合并机制见 design D2）；清除点=`_finish()`（注意它不置 running=false，须显式清）+ checkpoint 各终态 write + merging 完成写；切批 selecting 写时三键须已为 null
- [ ] 2.2 重试轮（回归失败重试，run_id 变更）：在 `phase="retrying"` 写进度处写入新预生成的 `run_id`（`worktree`/`batch_total` 不变），并把新 run_id 以形参传入重试 `run_code_fix` 调用，保证重试 run 在飞期间读侧解析的是当前轮 out 文件

## 3. 读侧：条级进度合成

- [ ] 3.1 `core/code_fix.py` `read_progress()` 增加 `item_done`/`current_item` 合成：`running=true` 且批上下文在场时调 `read_fix_out(worktree, run_id)` 取有效行，`item_done`=有效行按 `item_id` 去重后的条数；`current_item` 取最近一行并经**台账回查**（`read_items()`，批内条目核销前保持 open 且含 title/file/line）补全 `title`（可选 `line`），匹配失败或台账读异常降级仅含 out 行字段；规格 code-fix-item-level-progress 的「批内进行中合成」「零行」「损坏行」「批收尾让位」四 Scenario 全部落地
- [ ] 3.2 兜底：`running != true`、批上下文缺失、out 缺失/零行、`read_fix_out` 任何异常 → `item_done`/`current_item` 均为 null（MUST NOT 500、MUST NOT 回退 0/空对象）；缺新键的旧进度文件走同一兜底
- [ ] 3.3 新增 `tests/test_code_fix_item_level_progress.py`：覆盖上两条全部 Scenario（批上下文写入/清除、run 在飞期间上下文已在场的时序断言、合成、零行、损坏行、异常兜底、旧文件兼容、重试轮 run_id 刷新、batch_total 写入/清除），临时文件用 tmp_path（不落仓库内 basetemp）

## 4. Dashboard 转导层

- [ ] 4.1 `core/dashboard/data/code_review.py` `read_code_review_fix_progress()` 透传 `item_done`/`current_item`/`batch_total`（字段缺失补 null，形态对齐既有缺省态兜底口径）

## 5. 前端：条级进度文案

- [ ] 5.1 `CodeFixProgressCard.tsx`：类型补充新字段；`phase="fixing"` 且 `item_done` 非 null 时次级文案追加「本批已处置 N/M 条 · 刚完成：<status 中文>：<file> <title>」（M=`batch_total`；`batch_total` 为 null 时仅显示「本批已处置 N 条」）；`item_done` 为 null 且 `phase="fixing"` 时显示「批内明细尚未产生（agent 处置中）」；非 fixing 阶段不渲染条级区块（规格三 Scenario 全覆盖）
- [ ] 5.2 `npm run build` 通过（dist 产物为 reference，不入 Deliverables 硬门）

## 6. 收尾验证

- [ ] 6.1 定向测试全绿：`pytest tests/test_code_fix_item_level_progress.py` 及既有 code-fix / dashboard data 相关定向文件无回归

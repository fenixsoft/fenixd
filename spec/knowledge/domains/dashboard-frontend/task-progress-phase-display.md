<!-- knowledge: capability=task-progress-phase-display rev=2 sources=spec/archive/2026-09-11-add-task-progress-verify-phase,spec/archive/2026-09-26-add-quality-gates-visibility -->

# 任务进度按阶段呈现

SPEC 列表「任务进度」列的阶段感知展示：impl（蓝）/ verify（绿）/ gates（橙）三阶段，判定单点在后端。

## 现行规则

- 阶段判定单点在后端 summary 层：`spec_summary`（/api/specs 列表项）为每行输出 `progress_phase` 字段，判定优先级——`status == "testing"` 且 ocr 车道在飞（车道产物 `code-review.json` 可见 `status == "running"`）时为 `gates`；`status == "testing"`（ocr 车道非 running）时为 `verify`；`status == "implementing"` 且任务清单全勾（`task_total > 0` 且 `task_done == task_total`）且门禁数据可见（quality-gates.json 经 worktree 优先/主树读取可得）且门禁未全了结（`gates_done < gates_total`）时为 `gates`；其余一切状态（drafted/ready/implementing 且不满足上述条件/implemented/verified/bug-found/blocked/done/pushed）一律 `impl`。
- 辅助字段透传：每行同时透传 `verify_current`（取 `parse_verify_progress` 返回的 current，无则空串）与 `gates_current`（取门禁读侧合成的 current 文案，无则空串）；阶段判定不在前端重复实现（前端只消费字段，不自持状态映射）。
- impl 阶段渲染：蓝色 `#1677ff` 进度条、percent 取任务完成度、文案 `task_done/task_total` + 百分比、run 层实时线索（runAhead「run N/M 已汇报」/ runCurrent「进行中 …」）、列排序键为任务完成度——「显示什么按什么排」。
- verify 阶段渲染：绿色 `#52c41a` 进度条、percent 取验证完成度 `pct(verify_done, verify_total)`、文案 `verify_done/verify_total`、`verify_current` 非空时作辅助文案、impl run 层实时线索不显示（impl run 在进入 testing 前已结束）、排序键为验证完成度百分比。
- gates 阶段渲染：门禁专属橙色 `#fa8c16` 进度条、底轨淡橙（与 verify 阶段底轨淡绿同一做法）、percent 取门禁完成度 `pct(gates_done, gates_total)`、文案 `gates_done/gates_total`、`gates_current` 非空时作辅助文案、impl run 层实时线索不显示（gates 阶段语义上 impl run 的编码工作已结束）、排序键为门禁完成度百分比；impl 与 verify 两阶段渲染保持与既有路径一致（新增 gates 分支不触碰既有两分支）。
- 容错：验证进度损坏时（`parse_verify_progress` 返回 error、total/done 为 0）`progress_phase` 仍为 verify、`verify_current` 为空串、按 0 进度展示、不抛异常；门禁数据损坏（读侧全 unknown、gates_done 计 0）时 `progress_phase` 仍为 gates、按 0/6 容错展示，quality-gates.json 完全不可见（exists == false）则为 impl。
- fast-track 语义：fast-track SPEC 不停留 testing 态——implementing 期间满足条件同样进入 gates（收尾同样落盘门禁数据），run 结束 `_fast_track_advance_to_verified` 瞬时连转后状态离开 implementing，phase 不再为 gates；无需任何 mode 特判代码。

## 溯源

- [2026-09-11 add-task-progress-verify-phase](spec/archive/2026-09-11-add-task-progress-verify-phase/) — 建立阶段感知任务进度列：后端单点 `progress_phase`（testing→verify 绿色验证进度，其余 impl 蓝色零回归）与排序键同源
- [2026-09-26 add-quality-gates-visibility](spec/archive/2026-09-26-add-quality-gates-visibility/) — 新增 gates（橙）阶段两窗口：testing 且 ocr 车道 running 优先于 verify、implementing 任务全勾且门禁进行中；门禁数据损坏容错

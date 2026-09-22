# task-progress-phase-display 能力增量（add-quality-gates-visibility）

> 列表「任务进度」列的阶段感知展示契约扩展：在 impl（蓝）/verify（绿）两阶段之间新增 gates（橙）阶段——implementing 且任务全勾、门禁进行中时，主进度条以门禁专属橙色从零走门禁完成度。阶段判定单点仍在后端 summary 层，前端纯渲染。

## MODIFIED Requirements

### Requirement: 阶段判定单点在后端

列表行摘要（`spec_summary`，/api/specs 列表项）MUST 为每行输出 `progress_phase` 字段，判定优先级：`status == "testing"` 时为 `"verify"`；`status == "implementing"` 且任务清单全勾（`task_total > 0` 且 `task_done == task_total`）且门禁数据可见（quality-gates.json 经 worktree 优先/主树读取可得）且门禁未全了结（`gates_done < gates_total`）时为 `"gates"`；其余一切状态（`drafted`/`ready`/`implementing` 且不满足上述条件/`implemented`/`verified`/`bug-found`/`blocked`/`done`/`pushed`）一律 `"impl"`。同时 MUST 透传 `verify_current` 字段（取 `parse_verify_progress` 返回的 `current`，无则空串）与 `gates_current` 字段（取门禁读侧合成的 current 文案，无则空串）。阶段判定 MUST NOT 在前端重复实现（前端只消费字段，不自持状态映射）。

#### Scenario: 任务全勾且门禁进行中判定为 gates 阶段

- **WHEN** 某 implementing SPEC 的 tasks.md 全勾（task_done == task_total == 12）且 quality-gates.json 可见且 gates_done: 2, gates_total: 6
- **THEN** /api/specs 该行 `progress_phase` 为 `"gates"`，`gates_current` 为门禁读侧合成的当前进展文案（如「ocr 代码审查与处置：进行中」）

#### Scenario: 任务未全勾不进入 gates 阶段

- **WHEN** 某 implementing SPEC 的 task_done < task_total（哪怕 quality-gates.json 已存在）
- **THEN** 该行 `progress_phase` 为 `"impl"`（门禁进展只在详情页可见，列表主条仍走任务进度）

#### Scenario: 门禁全了结后回退 impl 阶段

- **WHEN** 某 implementing SPEC 任务全勾且 gates_done == gates_total == 6（全部 passed/skipped，尚待 merge 的间隙）
- **THEN** 该行 `progress_phase` 为 `"impl"`（gates 满格不滞留，等待 merge 后由状态推进接管）

#### Scenario: testing 状态判定为 verify 阶段

- **WHEN** 某 SPEC 的 STATE.md 状态为 `testing`（full 模式验证引擎运行中）
- **THEN** /api/specs 该行 `progress_phase` 为 `"verify"`，且 `verify_current` 为验证引擎写入的当前步骤文案（如「正在验证场景 …」）

#### Scenario: 非 testing 且非 gates 条件状态一律 impl 阶段

- **WHEN** 某 SPEC 状态为 `verified`、`done`、`pushed`、`bug-found`、`blocked`，或 `implementing` 但不满足 gates 条件（任务未全勾/门禁数据缺失/门禁全了结）
- **THEN** 该行 `progress_phase` 为 `"impl"`（含验证已结束的完成侧与 fix 循环/熔断态，均按 impl 处理）

#### Scenario: fast-track SPEC 门禁阶段同样可见

- **WHEN** 某 fast-track SPEC 在 implementing 且任务全勾、quality-gates.json 可见且未全了结（fast-track 收尾同样落盘门禁数据）
- **THEN** 观测到的 `progress_phase` 为 `"gates"`；run 结束 `_fast_track_advance_to_verified` 瞬时连转后状态离开 implementing，phase 不再为 gates

#### Scenario: 验证进度损坏时字段容错

- **WHEN** 某 testing SPEC 的进度文件损坏（`parse_verify_progress` 返回 `error` 字段，total/done 为 0）
- **THEN** `progress_phase` 仍为 `"verify"`，`verify_current` 为空串，不抛异常（渲染端按 0 进度容错展示）

#### Scenario: 门禁数据损坏不影响阶段判定

- **WHEN** 某 implementing SPEC 任务全勾但 quality-gates.json 损坏（读侧全 unknown、gates_done 计 0）
- **THEN** 该行 `progress_phase` 为 `"gates"`（门禁可见但未了结），渲染端按 0/6 容错展示；若 quality-gates.json 完全不可见（exists == false）则为 `"impl"`

## ADDED Requirements

### Requirement: gates 阶段渲染橙色门禁进度

前端列表「任务进度」列在 `progress_phase == "gates"` 时 MUST：进度条颜色为门禁专属橙色 `#fa8c16`、底轨淡橙（与 verify 阶段底轨淡绿 `TRACK_GREEN` 同一做法），percent 取门禁完成度 `pct(gates_done, gates_total)`；数值文案显示 `gates_done/gates_total`；`gates_current` 非空时作为辅助文案展示；impl run 层实时线索 MUST NOT 显示（gates 阶段语义上 impl run 的编码工作已结束）；列排序键 MUST 改为门禁完成度百分比，保持「显示什么按什么排」；impl（蓝）与 verify（绿）两阶段的既有渲染 MUST 与现状逐像素一致（零回归）。

#### Scenario: gates 阶段显示橙色门禁进度

- **WHEN** 某 implementing SPEC 的 `progress_phase: "gates"`、`gates_done: 2, gates_total: 6`、`gates_current: "ocr 代码审查与处置：进行中"`
- **THEN** 任务进度列渲染橙色进度条（约 33%）、淡橙底轨、文案 `2/6`、辅助文案含「ocr 代码审查与处置」；run 层线索不出现；点击列头排序按门禁完成度

#### Scenario: impl 与 verify 阶段渲染零回归

- **WHEN** 任一 `progress_phase == "impl"` 或 `"verify"` 的行按既有条件渲染
- **THEN** 颜色、文案、辅助信息、排序键与修复前完全一致（新增 gates 分支不触碰既有两分支的渲染路径）

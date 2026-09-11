# task-progress-phase-display 能力增量（add-task-progress-verify-phase）

> spec 列表「任务进度」列的阶段感知展示契约：仅 `testing` 状态切换为绿色验证进度，其余状态维持现状蓝色 impl 进度。阶段判定单点在后端 summary 层，前端纯渲染。

## ADDED Requirements

### Requirement: 阶段判定单点在后端

列表行摘要（`core/dashboard/data.py` 的 `spec_summary`，/api/specs 列表项）MUST 为每行输出 `progress_phase` 字段：`status == "testing"` 时为 `"verify"`，其余一切状态（`drafted`/`ready`/`implementing`/`implemented`/`verified`/`bug-found`/`blocked`/`done`/`pushed`）一律 `"impl"`。同时 MUST 透传 `verify_current` 字段（取 `parse_verify_progress` 返回的 `current`，无则空串）。阶段判定 MUST NOT 在前端重复实现（前端只消费字段，不自持状态映射）。

#### Scenario: testing 状态判定为 verify 阶段

- **WHEN** 某 SPEC 的 STATE.md 状态为 `testing`（full 模式验证引擎运行中）
- **THEN** /api/specs 该行 `progress_phase` 为 `"verify"`，且 `verify_current` 为验证引擎写入的当前步骤文案（如「正在验证场景 …」）

#### Scenario: 非 testing 状态一律 impl 阶段

- **WHEN** 某 SPEC 状态为 `verified`、`done`、`pushed`、`bug-found`、`blocked` 或 `implementing` 等任一非 testing 值
- **THEN** 该行 `progress_phase` 为 `"impl"`（含验证已结束的完成侧与 fix 循环/熔断态，均按 impl 处理）

#### Scenario: fast-track SPEC 恒为 impl 阶段

- **WHEN** 某 fast-track SPEC 在任意生命周期时刻（implementing 运行中、或 run 结束后 `_fast_track_advance_to_verified` 瞬时连转 testing→verified）
- **THEN** 观测到的 `progress_phase` 恒为 `"impl"`（fast-track 不停留 testing 态，无需任何 mode 特判代码即满足）

#### Scenario: 验证进度损坏时字段容错

- **WHEN** 某 testing SPEC 的进度文件损坏（`parse_verify_progress` 返回 `error` 字段，total/done 为 0）
- **THEN** `progress_phase` 仍为 `"verify"`，`verify_current` 为空串，不抛异常（渲染端按 0 进度容错展示）

### Requirement: verify 阶段渲染绿色验证进度

前端列表「任务进度」列在 `progress_phase == "verify"` 时 MUST：进度条颜色为绿色 `#52c41a`、percent 取验证完成度 `pct(verify_done, verify_total)`；数值文案显示 `verify_done/verify_total`；`verify_current` 非空时作为辅助文案展示；impl run 层实时线索（run 已汇报/进行中提示）MUST NOT 显示（impl run 在进入 testing 前已结束，线索无意义）；列排序键 MUST 改为验证完成度百分比，保持「显示什么按什么排」。

#### Scenario: 验证阶段显示绿色验证进度

- **WHEN** 某 testing SPEC 的 `verify_done: 5, verify_total: 11, verify_current: "正在验证场景 S-06"`
- **THEN** 任务进度列渲染绿色进度条（约 45%）、文案 `5/11`、辅助文案含「正在验证场景 S-06」；run 层线索不出现；点击列头排序按验证完成度

#### Scenario: 验证进度损坏时 0 进度容错

- **WHEN** 某 testing SPEC 的 `verify_total: 0`（进度文件缺失/损坏）
- **THEN** 任务进度列渲染绿色进度条 0%、文案 `0/0`、无辅助文案，不报错不空白

### Requirement: impl 阶段渲染零回归

前端列表「任务进度」列在 `progress_phase == "impl"` 时 MUST 与现状渲染完全一致：蓝色 `#1677ff` 进度条、percent 取任务完成度、文案 `task_done/task_total` + 百分比、run 层实时线索（runAhead「run N/M 已汇报」/ runCurrent「进行中 …」）与列排序键（任务完成度）全部不变。

#### Scenario: 实现阶段维持现状渲染

- **WHEN** 某 `implementing` SPEC 正常推进（task_done: 3, task_total: 8，run 层线索存在）
- **THEN** 任务进度列渲染蓝色进度条（约 38%）、文案 `3/8` + 百分比 + run 线索，与修复前逐像素一致

#### Scenario: 完成态回归蓝色 impl 进度

- **WHEN** 某 SPEC 验证通过进入 `verified` 或 `done`（impl 任务清单全勾）
- **THEN** 任务进度列重新显示 impl 进度（蓝色、100% 或任务清单实况），验证绿色条不再出现

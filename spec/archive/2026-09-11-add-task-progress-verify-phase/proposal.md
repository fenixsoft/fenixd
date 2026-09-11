# 列表任务进度条按 SPEC 阶段动态切换（add-task-progress-verify-phase）

## Why

full 模式 SPEC 的验证阶段（`testing` 状态）通常是整条流水线里最长的阶段（验证引擎逐场景推进），但 spec 列表「任务进度」列此时显示的是已 100% 勾选、静止不动的 impl 任务清单——进度条失去信息量，验证推进只能靠旁边「验证」列的裸数字感知。需要任务进度列按 SPEC 所处阶段动态切换：验证阶段显示验证场景进度（绿色），其余阶段维持实现任务进度（蓝色），SPEC 完成后回归 impl 进度蓝色。

## What Changes

- 后端列表行摘要（`core/dashboard/data.py` 的 `spec_summary`，/api/specs 列表项）新增两个透传字段：`progress_phase`（`"verify"` 仅当 `status == "testing"`，其余状态一律 `"impl"`；fast-track 因 `_fast_track_advance_to_verified` 瞬时连转 testing→verified、不停留，天然恒 `"impl"` 无需特判）与 `verify_current`（验证当前步骤文案，取 `parse_verify_progress` 的 `current`，如「正在验证场景 X」）。
- 前端列表「任务进度」列（`core/dashboard/static/src/pages/projects/list.tsx`）按 `progress_phase` 分支渲染：`"verify"` 时进度条变绿（`#52c41a`，antd success 色）、显示 `verify_done/verify_total` 与 `verify_current` 辅助文案、隐藏 impl run 层实时线索（impl run 已结束，线索无意义）；`"impl"` 时渲染路径与现状完全一致（蓝色 `#1677ff` + tasks.md 勾选 + run 线索）。
- 列排序跟随显示值：`"verify"` 阶段该列排序键改为验证完成度百分比，`"impl"` 阶段维持任务完成度——避免「显示 A 排序按 B」的错位。
- 阶段口径（用户已确认）：仅 `testing` 切绿色 verify；`verified`/`done`/`pushed` 算 SPEC 完成侧、`bug-found`/`blocked` 等其余状态按 impl 处理（蓝色）。
- 非目标：详情页不联动（已有独立「任务清单」「验证进度」两卡片）；不改「验证」列；不改状态机与验证引擎写入逻辑；fast-track 无专属处理分支。

## Capabilities

### New Capabilities

- `task-progress-phase-display`: spec 列表任务进度列的阶段感知展示契约——阶段判定（仅 testing → verify，单点在后端 summary 层）、两阶段各自的进度条颜色/数据源/辅助文案/排序键、impl 路径零回归。

### Modified Capabilities

（无——run-progress-observability（run 层线索）与 task-progress-sync（写侧同步）的既有语义不变，本 change 只是在其上叠加阶段分支。）

## Impact

- 代码：`core/dashboard/data.py`（`spec_summary` 加 2 个透传字段，约 5 行）；`core/dashboard/static/src/pages/projects/list.tsx`（任务进度列渲染分支 + 排序键，约 25 行）。
- 测试：`tests/test_dashboard_data.py`（`spec_summary` 的 phase 判定与字段透传：testing→verify、verified/done/bug-found→impl、verify_current 透传、fast-track spec 恒 impl）。
- 数据：零迁移，纯读侧/展示层。
- 下游：spec 列表「任务进度」列在 testing 阶段呈现验证推进实况（绿色），其余阶段视觉与行为与现状逐像素一致；与同日立项的 fix-verify-progress-fasttrack 改动面正交（该 spec 改 `parse_verify_progress` 数据源与本列的 `verify_done/verify_total` 取值质量，不碰列表渲染与 phase 判定），merge 顺序不敏感。
- 前端构建产物由框架 merge 后自动重建（dist 不入库）。

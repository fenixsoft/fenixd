# 设计：列表任务进度条阶段感知（add-task-progress-verify-phase）

## Context

- 列表「任务进度」列现状（`core/dashboard/static/src/pages/projects/list.tsx:748-795`）：恒渲染蓝色（`#1677ff`）Progress + `task_done/task_total` + run 层实时线索（`run_progress` 的 runAhead/runCurrent，fix-implementer-task-progress D3）；排序键 `pct(task_done, task_total)`。
- 数据源（`core/dashboard/data.py::spec_summary`，1866 行，/api/specs 列表项）：已调 `parse_verify_progress`（`vp`）产出 `verify_done/verify_total/verify_error`，已持有 `entry["status"]`——加 `progress_phase`/`verify_current` 两个字段是纯透传，无新增 IO。
- 状态机（`core/state_machine.py` SpecStatus）：`drafted→ready→implementing→implemented→testing→verified→done→pushed`，另有 `bug-found`（fix 循环）、`blocked`（熔断）。fast-track 经 `_fast_track_advance_to_verified`（`pm_engine/dispatch.py:1853`）瞬时连转 testing→verified，不停留 testing。
- 用户已确认口径：仅 testing 切绿色 verify；verified/done/pushed 算完成侧、bug-found/blocked 等按 impl；详情页不联动（已有独立两卡片）；fast-track 恒 impl。

## Goals / Non-Goals

**Goals**

- testing 阶段任务进度列呈现验证推进实况：绿色进度条 + `verify_done/verify_total` + `verify_current` 辅助文案。
- 其余一切状态渲染路径与现状逐像素一致（零回归）。
- 排序跟随显示值，消除「显示 A 排序按 B」错位。

**Non-Goals**

- 不改详情页（独立卡片已分语义）。
- 不改「验证」列（verdict Popover 等既有能力不动）。
- 不改状态机、验证引擎写入逻辑、fast-track 派发逻辑。
- 不做 verify 阶段的 run 层实时线索迁移（验证引擎的 current 文案已足够；verifier run 的任务协议解析属另一能力域）。

## Decisions

1. **阶段判定单点在后端 `spec_summary`，前端只消费 `progress_phase`**
   `"verify" if status == "testing" else "impl"` 一行三元，与 `verify_current` 透传同处返回 dict。
   *备选*：前端拿 `status` 自行判阶段——否决，状态→阶段映射属后端语义（与 STATE.md 单一事实源同侧），前端复刻会在下一次口径调整时双点漂移；且 `spec_summary` 是单测直接命中点，判定逻辑放后端测试成本最低。

2. **`verify_current` 直接透传 `vp.get("current", "")`**，前端非空才渲染。验证引擎 `_write_progress` 的 current 文案（推进中「正在验证场景 …」/终态「验证完成: …」）即天然的场景级实况；testing 阶段读到终态文案的概率极低（读到即转 verified），不做二次加工。

3. **渲染分支结构：复用现有 JSX 骨架，按 phase 换色值/数据/文案三元**
   Progress 的 `strokeColor`、percent、数值行内容按 `record.progress_phase` 三元切换；`runAhead/runCurrent` 仅在 impl 分支参与渲染。不抽新组件——列 render 函数内聚，两分支共享容器布局（minWidth/行高），改动面最小且 diff 一目了然。

4. **绿色取 `#52c41a`（antd 默认 success 绿）**，与既有 blue `#1677ff` 同为 antd 语义色，暗色主题下 antd Progress 自动处理轨道，无需额外主题分支。

5. **排序键按 phase 切换**：`sorter` 内 `(a, b) =>` 对每行先取该行 phase 对应的 pct 再比较（`phasePct(record) = phase === "verify" ? pct(verify_done, verify_total) : pct(task_done, task_total)`），混排时验证行与 impl 行各自按显示值归位。

## Risks / Trade-offs

- [verify_error（进度文件损坏）时 testing 行显示 0/0 绿条] → 与「验证」列的 ⚠ 异常提示互补（该列已有 Tooltip 错误详情）；任务进度列保持纯进度语义不重复报错，spec 场景已固化容错行为。
- [`verify_current` 中文文案含逗号/冒号，前端原样渲染] → 现有 Typography.Text 无格式假设，直显安全；文案由验证引擎单点产出，无注入面。
- [与 fix-verify-progress-fasttrack 的 merge 交互] → 该 spec 改 `parse_verify_progress`（本 change 只消费其返回值）与列表 `verify_done/verify_total` 的取值质量；`spec_summary` 与 `list.tsx` 任务进度列两侧改动行不相邻，冲突风险低；若真冲突，语义正交可机械合并。
- [testing 态短暂停留的 full 轮次（快速验证）切换闪烁] → 列表 2s watcher 心跳刷新，绿/蓝切换与状态转换同频，可接受；不做滞回。

## Migration Plan

纯读侧/展示层，无迁移。merge 后框架重建 dist 即生效；存量 testing SPEC 下一刷新即绿色。回滚 = revert 单 commit。

## Open Questions

（无——口径经用户确认，数据源与渲染点均已定位到行。）

# Proposal: add-command-center-spec-view

## Why

指挥中心「组织总览」屏目前只能实时观察在飞归属：产品团队汇总卡的「需求数量」是纯数字点不动，想按某个 SPEC 横向审视五线各车道的分工过程（每条车道跑过几轮、每轮对话内容）只能逐个项目翻时间轴。管理演示与跨项目复盘都需要「按 spec 看全组织」的视角。

## What Changes

- 产品团队汇总卡「需求数量」格变为可点击入口：弹出下拉菜单（搜索框 + 滚动列表）列出当前项目筛选 × 时间窗内的活跃 SPEC 名单（org 响应 `summary` 新增 `specs` 名单；跨项目同名以 `project/spec` 消歧，单项目视图只显 spec 名）。
- 选中 SPEC 后全板进入「spec 视图」：每张车道卡活动区切换为该车道对该 SPEC 的轮次列表（`spec名 · 第N轮`，全史编号、最新在前、在飞轮次照常可点），无 run 车道显「未运行」灰虚线框；点击任一轮打开该轮运行记录弹窗（复用 RunRecordModal）。
- 新增只读端点 `GET /api/command-center/spec-runs?project&spec&window`：返回花名册全量车道的轮次数据（全史定序 + 窗内出列两步收集）。
- spec 视图选中态深链进 URL（`spec` + `spec_project`），刷新/分享直达；再点「需求数量」退出；切项目/时间窗后 SPEC 不在新名单时自动退出。
- 既有实时模式行为零变动（attributables 三分渲染、指标 null→「—」口径、花名册/分区/汇报线全部不动）。

## Capabilities

### New Capabilities

（无——全部为既有能力的需求级修改）

### Modified Capabilities

- `command-center-aggregation`: 组织网格 org 响应 `summary` 新增 `specs` 名单（与 `spec_count` 完全同窗口口径，同循环派生）；新增 spec-runs 聚合（全史定序 + 窗内出列 + 花名册全量出列 + LANE_ALIASES 归并同口径）。
- `command-center-console-ui`: 组织总览屏新增 spec 视图显示模式（需求数量点击下拉、车道卡活动区轮次/未运行渲染、URL 深链与退出联动、静态渲染红线约束下的新列表）。

## Impact

- 后端：`core/dashboard/data/command_center.py`（`aggregate_org` 扩展 + 新聚合函数）、`core/dashboard/routes/command_center_routes.py`（新 GET 端点，表驱动追加注册）。
- 前端：`core/dashboard/static/src/pages/command-center/index.tsx`（specView 状态提升 + URL 同步）、`OrgGrid.tsx`（下拉 + 活动区 spec 视图分支）、`shared.ts`（纯函数/类型/色常量）、`services/dashboard.ts`（新 service 函数与类型）。
- 测试：`tests/test_command_center_aggregation.py`（后端聚合与端点）、`core/dashboard/static/tests/commandCenter.test.mjs`（前端纯函数，node --test type-stripping 直载）。
- 兼容性：org 既有键语义零变动（仅新增 `summary.specs`），五端点既有消费者不受影响；spec-runs 为纯只读新端点，遵守本模块「不新增 POST」约定。
- 设计真相源：`docs/superpowers/specs/2026-10-30-command-center-spec-view-design.md`（交互形态、红线、验收 Scenario 以它为准；该文档已过 builder 可建性审查与用户两项裁决：深链进 URL、轮次全史编号）。

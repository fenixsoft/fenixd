## Why

dsh 侧栏工作区行的 fenix 项目名称已有点击导航（fenix-dash-bridge-workspace-nav 能力），但悬停提示仍是 dsh 原生三行（名称 / 路径 / Created 时间），不含任何项目业务信息。用户想在不跳转的前提下于侧栏直接预览项目概况——简介、运行态、SPEC 状态分布、任务进度、活跃 Agent——而这些字段在 Dashboard 概览台账（ProjectTable）中已全部存在，且插件周期拉取的 `GET /api/projects` 端点本就返回全量 ProjectSummary（插件目前只解析了 name）。

## What Changes

- fenix 项目工作区行名称悬停（500ms，对齐原生延迟）时显示富提示深卡：名称 + 运行态胶囊、路径、简介（仅一行，空显示「暂无简介」）、非零 SPEC 状态胶囊（超过 4 个折叠为 +N）、`任务 x/y 个 · 活跃 Agent n 个`；数值 tabular-nums，无数据显示「—」不伪装 0。
- 视觉为用户定稿的「方案B 暗面胶囊」原型样式：深卡 `#2C2C2E`、16px 圆角（对齐 dsh 原生 tooltip 实测值），状态胶囊取 STATUS_META tone 的暗面同相派生色；零 animation/transition。
- 非 fenix 目录行维持 dsh 原生提示，零侵入（现有行为不变）。
- 拦截层点击行为不变（点击名称仍进项目详情深链）；fenix 行富提示激活期间原生三行提示互斥不出现（插件侧消解，不改原生 tooltip primitive）。
- 数据面：插件 `projectSync` 60s 周期任务从仅解析项目名改为保留精简 ProjectSummary 投影（description / daemon / hosting / exists / discovered / status_counts / task_done / task_total / active_runs）；fenixd 后端零改动。
- 跨仓交付形态照 ADR-339 先例（move-project-nav-to-workspace-rows）：宿主仓 dsh-plugins 直改 + 本仓 `plugin-patch/` 补丁镜像。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `fenix-dash-bridge-workspace-nav`: 在既有「工作区行项目名称导航」能力上新增悬停富提示 requirement（点击导航、路径优先匹配、锚点拦截、非 fenix 零侵入、60s 对齐等既有 requirement 不变）。

## Impact

- 代码：`/root/dsh-plugins/fenix-dsh-dashboard-bridge` 的 `src/client/projectSync.ts`、`src/client/panels.tsx`（新增 tooltip 渲染模块可选拆分）与 `tests/` 契约测试；fenixd 仓零代码改动。
- 风险面：宿主官方升级改 ProjectRow/DOM 锚时提示静默降级（与既有导航降级路径同构）；tooltip 数据依赖 `/api/projects` 可用性，端点失败时该行回退原生提示。
- 界面真相源：`spec/changes/add-workspace-row-project-tooltip/prototype/`（纯 HTML/CSS 仿样，视觉参照、无约束力）。

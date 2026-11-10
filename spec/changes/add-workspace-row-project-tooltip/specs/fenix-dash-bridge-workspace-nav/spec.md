## ADDED Requirements

### Requirement: 工作区行项目富提示浮层

fenix 项目工作区行（`data-row-key` 前缀 `workspace:` 且命中项目匹配）的名称文本悬停时，须显示项目富提示深卡；视觉与信息结构以 `spec/changes/add-workspace-row-project-tooltip/prototype/index.html` 为准（**界面以 prototype/ 为准**；该原型为纯 HTML/CSS 仿样，视觉参照、无约束力——DOM 实现形态由本 SPEC 决策约束，不要求逐类名复刻）。数据源为插件既有 `GET <prefix>/api/projects` 响应中的 ProjectSummary 字段，fenixd 后端零改动。

#### Scenario: 悬停显示富提示

- **WHEN** 用户在 fenix 项目工作区行名称上悬停约 500ms（对齐原生 tooltip 延迟）
- **THEN** 行右侧浮出深卡富提示，自上而下含：项目名 + 运行态胶囊、路径、简介一行、SPEC 状态胶囊组、`任务 x/y 个 · 活跃 Agent n 个` 统计行
- **AND** 深卡为暗面样式：底 `#2C2C2E`、圆角 16px、标题 `#fff` 14px/20px、次文本 `#cfd3d6` 12px/16px（dsh 原生 tooltip 实测值）

#### Scenario: 简介一行截断与空口径

- **WHEN** 项目 description 非空且超长
- **THEN** 仅显示一行，超出截断（CSS ellipsis）
- **WHEN** description 缺失或为空
- **THEN** 显示「暂无简介」（与概览台账口径一致）

#### Scenario: 状态胶囊组

- **WHEN** status_counts 存在非零状态
- **THEN** 按 STATUS_META 的 状态→tone 映射渲染 999 胶囊（12px、暗面同相派生色），仅显示非零项
- **WHEN** 非零状态超过 4 个
- **THEN** 折叠为前 4 个胶囊 + `+N` 摘要胶囊
- **WHEN** 全部状态为零或字段缺失
- **THEN** 不渲染胶囊组区域

#### Scenario: 任务与活跃 Agent 统计行

- **WHEN** task_total / task_done / active_runs 有数值
- **THEN** 显示 `任务 {task_done}/{task_total} 个 · 活跃 Agent {active_runs} 个`，数值 tabular-nums
- **WHEN** 字段缺失（null/undefined）
- **THEN** 对应数值显示「—」；字段存在且为真实 0 时照常显示 `0`

#### Scenario: 非 fenix 行零侵入

- **WHEN** 悬停未命中项目匹配的工作区行（如非 fenix 目录）
- **THEN** 维持 dsh 原生 tooltip（名称/路径/Created 时间），无富提示、无额外 DOM 注入

#### Scenario: 点击行为不变

- **WHEN** 用户点击富提示所覆盖的行名称区域
- **THEN** 既有拦截层行为不变——仍触发项目详情深链（`fenix-project-<name>`），富提示不吞点击

#### Scenario: 数据失效回退原生

- **WHEN** `/api/projects` 拉取失败或该项目摘要字段缺失（exists:false / error 降级项）
- **THEN** 该行回退 dsh 原生 tooltip，不渲染残缺富提示

#### Scenario: 静态渲染红线

- **THEN** 富提示的显隐切换零 CSS animation/transition（纯 display/visibility 切换）

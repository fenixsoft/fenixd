## Why

项目页（`/projects/:name`）目前是「一屏到底」的单一 SPEC 列表：所有信息——SPEC 进度、以及项目级的自由会话入口——都堆在同一页。随着项目级能力增多（会话、未来的质量视图），单页结构既放不下新内容，也让用户在「看 SPEC」和「开会话」两种意图之间来回滚动。用一个 Tabs 容器把项目页按用途分面（开发 / 质量 / 会话），是让页面结构随能力增长而扩展的最小改动。

同时，现有「接入会话」是一个全屏 Modal，从标题栏按钮弹出。会话是项目级的一等视图而非临时弹窗，把它降为一个常驻 Tab 的内容，用户切过去即可对话，语义更顺。

## What Changes

- 项目页（`pages/projects/list.tsx`）在**项目名称下方**引入 `Tabs` 控件（antd `Tabs`，`items` 形态），承载三个分面：
  - **开发**（默认选中）：即当前的 SPEC 列表（搜索/筛选条 + 桌面表格 / 移动端卡片），内容零回归。
  - **质量**：暂时留空，渲染空态占位（`Empty` + 建设中文案）。
  - **会话**：把原「接入会话」Modal 的会话界面（消息流 + 输入区 + 开始/停止）以内联面板形态搬入此 Tab。
- **移除**标题栏右端的「接入会话」按钮：会话能力由「会话」Tab 承载，不再保留 Modal 入口。
- 会话界面的**交互语义不变**：切到「会话」Tab 时若会话未启动，仍显示「开始会话」按钮、点击才启动进程（不隐式启进程）；消息流仍复用 `runEventsToChatMessages` + `ClaudeMessageList`；发送/停止/终态提示行为与既有 Modal 一致。
- Tab 选中态**不持久化**到 URL：刷新后回到默认的「开发」Tab。
- 会话对外行为（创建/复用、发送、订阅、终止）**零变更**——本变更只改会话界面的承载形态（Modal → Tab 内联面板），不改会话进程管理与 REST/SSE 契约。

## Capabilities

### New Capabilities
- `project-page-tabs`: 项目页的分面导航——项目名称下方的 Tabs 容器、三个分面（开发 / 质量 / 会话）的职责与切换规则、默认分面、以及「质量」空态占位约定

### Modified Capabilities
- `dashboard-live-session`: 会话界面的**承载形态**由「标题栏按钮 + 全屏 Modal」改为「项目页『会话』分面的内联面板」；入口位置与呈现方式的 Requirement 相应改写（会话创建/复用/发送/订阅/终止的行为契约不变）

## Impact

- **前端（本项目交付物）**：
  - `core/dashboard/static/src/pages/projects/list.tsx`：引入 `Tabs`（已 import，未使用），用 `items` 组织三分面；SPEC 列表整体下沉为「开发」分面；移除标题栏会话按钮与 `sessionOpen` 状态
  - 新增 `core/dashboard/static/src/pages/projects/components/SessionPanel.tsx`：由 `SessionModal.tsx` 迁移而来的内联会话面板（去掉 `Modal` 外壳，保留全部会话逻辑）
  - 删除 `core/dashboard/static/src/pages/projects/components/SessionModal.tsx`（内容迁入 SessionPanel，Modal 形态废弃）
- **前端（非交付物）**：`core/dashboard/static/dist/`（构建产物）由框架在合并后重建；不新增前端单测依赖（本项目前端测试当前仅覆盖纯函数模块，组件级验证走浏览器 E2E）
- **后端 / API / 数据结构**：无变更。`/api/session/*` 端点、`session_manager`、SSE 契约与 STATE.md 均不动
- **非目标**：
  - 不实现「质量」Tab 的任何内容（仅空态占位）
  - 不新增会话功能（多会话、会话历史、会话与 SPEC 绑定等）
  - 不改「会话」之外的任何既有 Tab 行为（本次仅一个容器、一个真实分面）
  - 不做 Tab 状态持久化 / 深链接

# Proposal: add-project-architecture-tab

## Why

Dashboard 项目详情页现有页签（功能开发 / 代码审查 / 测试回归 / 会话接入）全部面向「开发过程」，没有一个地方能让用户快速看懂**一个项目本身长什么样**：核心组件有哪些、主链路怎么跑、依赖了哪些外部服务、信任边界在哪。引入 archify（`npx skills add tt-a1i/archify -g`，产出自包含交互式 HTML 架构图）后，这个空白可以用很低成本补上——daemon 已有按项目 spawn headless claude 的成熟先例（session_manager / regression autodraft），把「分析项目 → 生成架构图」做成一个按需按钮触发的页签即可。

## What Changes

- **新增「项目架构」页签**：位于项目详情页「测试回归」之后、「会话接入」之前；所有注册项目一视同仁（无项目级特殊处理）。
- **按需生成，不自动生成**：页面不自动触发分析；从未生成过时展示空态 + 「刷新架构图」按钮，用户点击后才 spawn 一次性 headless claude（挂 archify skill）读项目代码产出架构图。
- **生成产物**：archify 自包含交互式 HTML，按项目存于 `.fenix/architecture/`（运行时产物，gitignored），经后端 API 下发，前端 iframe 沙箱渲染。
- **图的形态契约**：8–16 个核心组件；突出一条主要路径；标出外部依赖与信任边界；辅助信息放说明卡片，**不继续增加连线**；中文标注。
- **生命周期**：状态机 `none → generating → ready | failed`；per-project 单飞（生成中再次点击拒绝）；超时进程组击杀；daemon 重启后残留 generating 态读侧合成为中断。
- **不新增配置项**：超时等均为模块常数（对齐 autodraft 先例），无 Dashboard 设置 UI 负担。

## Capabilities

### New Capabilities

- `project-architecture-diagram`: 项目架构图的触发（仅手动按钮）、生成机制（一次性 headless claude + archify skill + 单飞 + 超时治理）、产物契约（8–16 组件 / 单一主路径 / 外部依赖与信任边界 / 说明卡片承载辅助信息）、存储与 API 下发、前端页签渲染（空态 / 生成中 / 就绪 / 失败四态）。

### Modified Capabilities

<!-- 无：既有页签（代码审查/测试回归/会话接入）行为不变，list.tsx 仅插入一个新页签项。 -->

## Impact

- **后端**：`core/dashboard/routes/` 新增 `architecture_routes.py`（3 端点：status / refresh / diagram），`core/dashboard/server.py` 接线 mixin。
- **前端**：`core/dashboard/static/src/pages/projects/components/` 新增 `ArchitectureTab.tsx`；`list.tsx` 页签插入；`services/dashboard.ts` 新增 API 函数。
- **运行时目录**：各项目根 `.fenix/architecture/`（gitignored，非交付物）。
- **外部依赖**：archify skill（首次使用时自动 `npx skills add tt-a1i/archify -g`，失败给出人工安装提示）；spawn 走 ambient `claude` CLI（无新配置项）。
- **文档**：`docs/help/08-dashboard.md` 补「项目架构」页签说明。

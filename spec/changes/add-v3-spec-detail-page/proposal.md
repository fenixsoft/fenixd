# Proposal: add-v3-spec-detail-page

## Why

v3 SPEC 列表页目前只能查看概要行，无法查看单个 SPEC 的验证结论、任务清单、运行时间轴、场景结果、Bug 与失败截图——这些是 v1 详情页（如 `#spec/fenixd/refactor-core-packages`）的核心能力，也是日常跟踪 SPEC 执行的主要界面。迁移至 v3 后 v1 可完整退役。

## What Changes

- v3 新增路由 `/projects/:name/:spec`（spec 详情页）；SPEC 列表页的 spec 标题可点击进入。
- 迁移 v1 详情页全部功能区块：
  - **常驻顶部**：状态、优先级/创建/更新/依赖元信息、error 横幅、验证结论（verdict）、验证进度、Token 用量、任务清单（含勾选状态）。
  - **四个页签**：运行时间轴（时间线 + 运行节点，运行可查看 LLM 对话流）、场景结果（场景卡片 + 断言明细 + 通过/警告/失败/错误汇总）、Bug 列表（severity/source/描述/关联场景/证据/缩略图）、失败截图（缩略图 + 点击放大 lightbox）。
  - 页签空态语义对齐 v1（如"场景结果页签区分 report.json 损坏 vs 无场景结果"）。
- 数据复用现有后端：`GET /api/specs/<spec>?project=<name>`（详情聚合）、`/screenshots/<project>/<spec>/<file>`（截图，已有防穿越保护）、`/api/runs/<run_id>/watch` 系（运行对话流，v1 同源）；**后端零改动**。
- 页面控件由实现方探索合适的 ant design 组件（Tabs / Timeline / Steps / Table / Image / Descriptions 等），但须满足本文 spec 的行为 Scenario。

## Capabilities

### New Capabilities

- `v3-spec-detail-page`: v3 SPEC 详情页的入口、常驻信息区、四个页签及其空态语义、运行对话流查看。

## Impact

- **前端**：`core/dashboard/static/v3/src/pages/projects/`（新增 detail 页面与组件）、`config/routes.ts`（新路由）、`src/services/dashboard.ts`（详情/运行流封装）。
- **后端**：无改动。

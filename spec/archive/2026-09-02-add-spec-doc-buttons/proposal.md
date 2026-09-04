## Why

用户在跨项目 Web 仪表盘的 SPEC 列表页无法直接查看每个 SPEC 的提案文档（proposal.md）与设计文档（design.md），需要自行到文件系统翻阅。当前列表页只提供状态、进度等摘要，信息不完整；详情页（`#spec/<proj>/<spec>`）也仅展示运行时间轴 / 场景 / Bug 等运行时数据，不包含这两份核心设计文档。

## What Changes

- 在 SPEC 列表页（`#project/<name>` 视图）的每一行 SPEC 内增加「背景」「设计」两个操作按钮，分别对应 `proposal.md` 与 `design.md`。
- 点击按钮在当前页弹出 Modal，以 Markdown 渲染对应文档内容（复用现有 vendored marked 渲染器）；按钮始终可见，文档缺失时展示空态提示。
- 新增后端 API 端点，按项目 + SPEC 名称读取 `spec/changes/<spec>/` 下的 `proposal.md` / `design.md` 原文返回给前端。
- 行点击进入详情页的既有交互保持不变；按钮点击需阻止冒泡，避免误触发行跳转。

## Capabilities

### New Capabilities
- `spec-doc-view`：向仪表盘提供 SPEC 文档（proposal.md / design.md）内容读取的 API 端点，并定义缺失文件的响应语义。

### Modified Capabilities
- `dashboard-spec-table`（`spec/changes/add-dashboard-spec-table/specs/dashboard-spec-table/spec.md`）：SPEC 表格每行新增「背景」「设计」按钮及 Markdown 文档展示 Modal；按钮点击不触发行跳转。

## Impact

- 后端：`core/dashboard/server.py` 新增 API 路由；`core/dashboard/data.py` 增加读取 change 目录文档文件的逻辑。
- 前端：`core/dashboard/static/app.js`（表格行渲染、Modal 组件、API 调用）；`core/dashboard/static/index.html`（Modal 容器）；`core/dashboard/static/style.css`（Modal、按钮样式）。
- 依赖：复用现有 vendored marked 渲染器，无新增外部依赖。
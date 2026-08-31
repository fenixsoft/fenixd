# Proposal: improve-v3-spec-doc-markdown

## Why

v3 SPEC 列表页的「文档」按钮当前以纯文本 `<pre>` 展示文档原文，未渲染 Markdown，且三份文档共用一次性展示逻辑，与 v1 文档弹窗（需求背景/详细设计/任务清单三页签 + GFM Markdown 渲染 + 缓存）存在功能差距。补齐后 v3 的文档查看体验对齐 v1。

## What Changes

- 「文档」弹窗升级为完整 Markdown 渲染：`GET /api/spec-doc?project&spec&doc=<proposal|design|tasks>` 返回的 Markdown 原文渲染为富文本（GFM 语法：标题/列表/表格/代码块/链接等）。
- 三页签（需求背景 proposal / 详细设计 design / 任务清单 tasks）各自独立懒加载并缓存，切换页签不重复请求（语义对齐 v1 docCache）。
- 空文档（`found: false`）与加载失败分别给出可区分的空态/错误态（对齐 v1 emptyDocHtml / errorDocHtml 语义）。
- 渲染库采用 react-markdown + remark-gfm（或实现方论证等价方案），链接仅放行 http/https/mailto（对齐 v1 的安全渲染策略）。

## Capabilities

### New Capabilities

- `v3-spec-doc-view`: v3 SPEC 文档弹窗的三页签懒加载、Markdown 渲染、缓存与空态/错误态语义。

## Impact

- **前端**：`core/dashboard/static/v3/src/pages/projects/list.tsx`（文档弹窗部分重构为独立组件）、`package.json`（新增 markdown 渲染依赖）、dist 重构建。
- **后端**：无改动（`/api/spec-doc` 已返回 `{found, content}`）。

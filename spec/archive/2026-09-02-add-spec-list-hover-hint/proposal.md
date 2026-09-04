# Proposal: Dashboard SPEC 列表 —— 名称 hover 显示 Why 提示 + 「错误」列改为信息子行

## Why

Dashboard 项目视图的 SPEC 列表有两个可读性缺陷：

1. 用户看到一排 SPEC 名称，但不知道每个 SPEC 的背景动机（proposal.md 的 Why 部分）。想看必须点击「背景」按钮打开弹窗，成本高；SAAS 式列表常见的做法是 hover 名称即出摘要。
2. 最后一列「错误」只占一小列宽，内容被截断到 50 字符还要靠浏览器 title 才能看全，消息一长根本读不清；且这些消息（如 `Recovered from interrupted state`）多数是说明性信息而非报错，叫「错误」名不副实。

## What Changes

- **名称 hover 提示（Why hint）**：鼠标悬停 SPEC 名称单元格时，出现一个 div 模拟的悬浮提示（非浏览器 title），内容为该 SPEC `proposal.md` 中 `## Why` 段的 markdown 渲染结果。数据按需获取：首次 hover 时调用现有 `/api/spec-doc?doc=proposal` 取原文 → 前端提取 `## Why` 段 → 用现有 vendored `marked` 渲染 → 按 (project, spec) 内存缓存，后续 hover 零延迟。提取在渲染前于 markdown 源文本上完成，保留 markdown 语义。
- **「错误」列改为信息子行**：移除表格最后一列「错误」（含其排序键），当 SPEC 的 `error` 字段非空时，在该行下方渲染一个跨全列的完整信息行，消息完整显示、自动换行，不再截断；消息为空时不渲染子行。列标签语义由「错误」改为「信息」。

## Capabilities

### New Capabilities
<!-- 无新增能力 -->

### Modified Capabilities
- `dashboard-spec-table`: SPEC 列表表格交互与信息展示行为变化 —— 新增名称 hover Why 提示；「错误」列移除，改为行下方跨列信息子行；排序键 `error` 移除。

## Impact

- **前端**：`core/dashboard/static/app.js`（`renderProject` 表头、`specRow` 行渲染与错误单元格、`sortValue`/`sortSpecs` 排序键、新增 hover hint 逻辑与 fetch/缓存/定位）；`core/dashboard/static/style.css`（hint 容器与信息子行样式）。
- **服务端/API**：零改动，复用 `GET /api/spec-doc` 与同目录 `mdRender` 渲染管线。
- **测试**：`tests/test_dashboard.py` 无前端断言，服务端行为不变；改动后运行回归测试确认无破坏。
- **行为边界**：proposal.md 缺失或不存在 `## Why` 段 → 不显示提示；`error` 为 `null`/空 → 不渲染信息子行。
# Design: add-v3-spec-detail-page

## Context

- v1 详情页基线（`app.js` renderSpec ~1116 行起）：常驻区 = renderVerdict/renderVerify/renderTokenUsage/renderTasks；页签 = timeline（mountTimeline + run watch）/scenarios/bugs/screenshots；数据 `/api/specs/<spec>?project=`（spec_detail 聚合：verdict、verify、tasks、timeline、scenarios、bugs、screenshots、token_usage 等，字段以真实响应为准）。
- v3 已有：spec 列表页（入口改造点）、SSE 封装模式、`/screenshots/` 后端防穿越静态服务、`/api/runs/<run_id>/watch` 运行流端点（v1 在用）。

## Goals / Non-Goals

- Goals：v1 详情页全部信息区块与四页签在 v3 等价呈现；运行对话流可查看。
- Non-Goals：不实现 v1 的 morphdom 增量渲染机制（React 自身 diff 足够）；不迁移 run watch 的全部交互细节（滚动跟随等可简化，但对话流内容与"按需加载"语义必须保留）；不做 spec 的操作按钮（操作在列表「更多」）。

## Decisions

- **D1 路由与入口**：`/projects/:name/:spec` → `pages/projects/detail.tsx`；列表页名称列加点击跳转（`history.push`）；PageContainer `onBack` 返回列表。
- **D2 常驻区实现**：验证结论/验证进度 → `Card` + `Steps`/`Progress`/`Tag` 组合；Token 用量 → `Statistic`；任务清单 → 分组 `List` + 只读 Checkbox 样式。字段名以 `/api/specs/<spec>` 实际响应为准（实现时先观察真实 JSON 再对齐，v1 取值路径见 renderVerdict/renderVerify/renderTokenUsage/renderTasks）。
- **D3 页签**：antd `Tabs`（四页签恒可见），空数据页签渲染 Empty + v1 同款文案；scenarios 的损坏/无数据两种空态区分。
- **D4 时间轴**：antd `Timeline`；状态节点与运行节点混排（按 time 排序，数据源已含 `{kind: 'state'|'run'}`）；运行节点展开 → 内嵌 RunStream 子组件：打开时经 `/api/runs/<run_id>/watch?tail=…` 拉尾部 + SSE `run_events`（`run_id` 匹配）增量追加，卸载关连接；v1 的 thinking 折叠（collapseThinkingTokens）语义保留（思考块默认折叠）。
- **D5 截图**：antd `Image.PreviewGroup` + `Image`（自带 lightbox），src 为 `/screenshots/<project>/<spec>/<file>`。
- **D6 场景卡片**：`List`/`Card` + 状态色点（复用 Badge 风格）+ 断言明细 `Collapse`/条件渲染；汇总行用 `Tag` 计数。
- **D7 Bug 卡片**：`Card` + severity Tag + 证据文本 + 截图缩略图（Image，点击进 PreviewGroup）。

## Risks / Trade-offs

- `/api/runs/<run_id>/watch` 的响应结构（事件数组 + 游标语义）在 v1 是隐式契约：实现前先在浏览器观察真实响应与 SSE `run_events` 帧结构再写解析。
- 大 timeline（数百事件）渲染性能：antd Timeline 足够；若实测卡顿再做按运行节点折叠。
- token_usage 的成本字段可能缺省（网关未回传）：必须实现"成本不可用"降级文案。

## Migration Plan

services 封装 → 路由与页面骨架（常驻区）→ 四页签逐个实现（timeline 最重，含 RunStream）→ 入口接通 → 浏览器对照 v1 同 spec 逐区块走查。

## Open Questions

- 无（控件细节授权实现方探索，行为以 spec Scenario 为准）。

## Why

运行记录是用户观察 agent 行为的主窗口，但当前展示噪声淹没主线。对 3 份已完成 spec 的真实 run 流量化：最大一份 impl run 渲染 1499 项中，工具卡片占 33%（其中 Bash 247 个）、折叠成「已思考数秒」的 thinking 块占 14%、零信息心跳行（`[tool_progress]`/`[status]`/`[provider_marker]` 等）占 10%，真正的 assistant 叙述正文仅占 6%。且默认 tail=300 只覆盖大 run 的 20%，其中 15% 预算还被心跳事件吃掉。用户无法快速回答「agent 正在干什么」。

## What Changes

- **心跳行降噪与语义化（P0）**：`runEvents.ts` 对结构化事件分类处理，替代当前「无字符串 content 一律落 `[label]` 裸行」的兜底：
  - 静默丢弃：`tool_progress`（30 秒一条存活心跳）、`background_tasks_changed`、`commands_changed`、`run_metrics`、`init`、非错误 `stderr`。
  - 渲染为一行有信息的系统条：`provider_marker` → 模型路由信息（model@provider + chain 位置）；`transient_retry` → 瞬断告警（原因 + 退避 + 重试序号）；`compact_boundary` → 上下文压缩（pre→post tokens）；`vcs_state_changed(commit)` → 提交摘要。
  - `task_started` / `task_notification` 不再渲染独立行，凭共享 `tool_use_id` 回填到对应 Task 工具卡片（描述/状态/summary）。
  - 被静默的事件不再打断连续同名工具分组（`rendersNothing` 语义扩展）。
- **工具卡片语义化聚合（P1）**：分组维度从「同名连续」升级为「同类连续」——连续 Read/Grep/Glob 聚成「查阅 N 个文件」、连续 Bash 聚成「执行 N 条命令」（组内每条一行：摘要 + 成败标记）、连续 Edit/Write 聚成「编辑 N 个文件」（去重路径列表）。卡片 preview 优先取输入的 `description` 字段（agent 写的意图），无则回落命令/路径原文。利用 `tool_progress` 心跳携带的 `parent_tool_use_id` + `elapsed_time_seconds` 在卡片上标注工具耗时（长命令一眼可辨）。
- **thinking 展示与开场可见性（P2）**：
  - thinking 折叠头从恒定的「已思考数秒」升级为：相邻 assistant 事件 timestamp 差估算时长（「已思考 12 秒」）+ 首行内容预览，点击展开全文。
  - 面板头部新增「显示思考过程」开关（默认关）；保留兜底：run 无任何 text 正文时（deepseek 系全程 thinking）仍显示 thinking。
  - 「加载更早事件」分页：默认仍取尾部窗口，提供向前翻页；头部显示「显示尾部 N / 共 M 条事件」。后端 run tail 读取支持窗口化读取（offset 或分段），不再只有 deque 尾部截取。
- 前端构建产物随源码更新（`npm run build`，dist 为构建产物非交付物）。

## Capabilities

### New Capabilities

- `run-stream-noise-reduction`: run 流事件到聊天气泡的转换中对结构化事件做分类渲染——心跳类静默、信息类语义化、任务生命周期回填到工具卡片，替代 `[label]` 裸行兜底。
- `run-stream-tool-grouping`: 工具调用按同类连续聚合展示，卡片摘要优先语义描述并标注耗时。
- `run-stream-thinking-and-scope`: thinking 折叠头带时长与内容预览、思考显示开关（含无正文兜底）、运行记录向前分页与总量计数。

### Modified Capabilities

（无——`spec/specs/` 当前为空，运行记录相关历史能力均已归档且需求不兼容旧口径。）

## Impact

- **前端（主战场）**：`core/dashboard/static/src/components/claude-msg/` 下 `runEvents.ts`（事件分类）、`toolGrouping.ts`（同类聚合）、`ToolCard.tsx`（摘要/耗时）、`Reasoning.tsx`（时长/预览）、`ClaudeOutputPane.tsx`（开关/分页/计数）、`types.ts`（ChatMessage 扩展字段）；消费方 `detail.tsx`、`RunRecordModal.tsx`、`AdminInvokeModal.tsx`、`AdminRunModal.tsx` 的 props 适配。
- **后端**：`core/dashboard/data/runs.py` run tail 读取支持向前分页窗口；路由层与 `dashboard.ts` service 透传分页参数。
- **测试**：`core/dashboard/static/tests/` 下新增/扩展 node:test 单测（沿用 sessionEvents.test.mjs 的零依赖直载 .ts 模式）；后端 `tests/test_dashboard_api.py` 补 tail 分页用例。
- **无破坏性变更**：事件 jsonl 落盘格式不变，纯读侧（渲染端）改造；所有既有入口（时间轴内嵌/全屏弹窗/admin 弹窗）行为兼容。

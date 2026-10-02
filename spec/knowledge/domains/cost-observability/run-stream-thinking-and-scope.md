# 思考过程呈现与运行记录窗口
<!-- knowledge: capability=run-stream-thinking-and-scope rev=1
     sources=spec/archive/2026-09-27-add-run-record-readability -->

thinking 折叠头带时长与内容预览、全局思考显示开关（含无正文兜底），运行记录面板支持向前分页与总量计数。

## 规则

- **thinking 折叠头（静态回放）**：显示时长 + 内容预览。时长用该 thinking 所在 assistant 事件与下一个 assistant 事件的 `timestamp` 差估算（秒，四舍五入）；下一事件或时间戳缺失时显示「已思考数秒」，不显示 NaN 或负数。内容预览为 thinking 文本首行（截断至约 40 字符），格式如「已思考 12 秒 · 先看 queue.py 的派发逻辑…」。流式思考中沿用「思考中…」展示；展开后呈现完整思考全文。
- **思考显示开关**：运行记录面板提供全局「显示思考过程」开关，默认关闭；关闭时 thinking 折叠块不渲染且不打断工具分组。开关状态在会话内保持（组件重挂载不丢失，持久化到 localStorage 可选）。
- **无正文兜底**：run 流中不存在任何含非空 `text` 块的 assistant 事件时（deepseek 系全程无正文形态），无论开关状态必须渲染 thinking 块，避免界面看似「无 LLM 输出」。
- **向前分页与总量计数**：面板显示「显示尾部 N / 共 M 条事件」（N 为当前已加载条数，M 为 run 流总事件行数）。「加载更早事件」每次向前加载一批（默认批大小 300），新内容前置追加且不丢失已渲染内容与滚动位置主体；重复操作可到达流开头，到达后操作置为不可用；加载期间展示加载态。
- **后端窗口化读取**：`getRunTail` 既有语义不变（缺省取尾部 `max_lines` 条 + status），新增向前翻页参数（返回指定窗口的事件与总行数）；`stderr` 行容错语义沿用；翻页参数缺省时不影响既有消费方。

## 溯源

- 2026-09-27 2026-09-27-add-run-record-readability（spec/archive/2026-09-27-add-run-record-readability） — 新增 thinking 折叠头时长/预览、全局思考开关与无正文兜底、运行记录「加载更早事件」向前分页与总量计数、后端窗口化读取参数。

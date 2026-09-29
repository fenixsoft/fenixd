# Run 流工具聚合与卡片语义摘要
<!-- knowledge: capability=run-stream-tool-grouping rev=1
     sources=spec/archive/2026-09-27-add-run-record-readability -->

工具调用按「同类且连续」聚合展示，卡片摘要优先取 agent 的意图描述，并用心跳数据标注工具耗时。

## 规则

- **工具同类连续聚合**：查阅类（`Read`/`Grep`/`Glob`）→ 分组标题「查阅 N 个文件/模式」；命令类（`Bash`）→「执行 N 条命令」；编辑类（`Edit`/`Write`）→「编辑 N 个文件」（组内按路径去重展示，展开可见全部调用）；其他工具沿用既有同名连续分组逻辑。「连续」判定与既有逻辑一致：被渲染项分隔即断组（被静默的事件不算分隔）；N < 阈值 2 时不聚合、逐条展示；展开/收起交互沿用既有分组容器。
- **工具卡片语义摘要**：收起态摘要优先取工具输入的 `description` 字段（agent 写的意图描述）；缺失时按工具类型回落——Bash 用 `command` 原文、文件类工具用 `file_path`/`path`，其余沿用既有 `summarize` 兜底。摘要超长单行截断省略，不换行撑高。
- **工具耗时标注**：利用 `tool_progress` 心跳事件（含 `parent_tool_use_id` 与 `elapsed_time_seconds`）计算各工具调用的已观测耗时，标注在对应工具卡片或分组内条目上（格式如「8m30s」）。同一 `tool_use_id` 多条心跳取最大 `elapsed_time_seconds`；无心跳覆盖的工具（快速完成）不显示耗时标注。聚合分组在组内每条命令行上展示各自成败与耗时。

## 溯源

- [2026-09-27 2026-09-27-add-run-record-readability](spec/archive/2026-09-27-add-run-record-readability/) — 分组维度由「同名连续」升级为「同类连续」三类映射，新增 description 优先语义摘要与心跳耗时标注（组内逐条成败+耗时）。

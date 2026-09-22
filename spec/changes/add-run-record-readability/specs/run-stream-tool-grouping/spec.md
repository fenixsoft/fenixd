## ADDED Requirements

### Requirement: 工具同类连续聚合

系统 SHALL 将「同类且连续」的工具调用聚合为一个分组项展示，同类映射：

- 查阅类：`Read`、`Grep`、`Glob` → 分组标题「查阅 N 个文件/模式」
- 命令类：`Bash` → 分组标题「执行 N 条命令」
- 编辑类：`Edit`、`Write` → 分组标题「编辑 N 个文件」（组内按路径去重展示）
- 其他工具沿用既有同名连续分组逻辑

「连续」判定与既有逻辑一致：被渲染项分隔即断组（含不可见项例外，见噪声抑制能力）。N < 阈值 2 时不聚合、逐条展示。展开/收起交互沿用既有分组容器。

#### Scenario: 间隔 thinking 的连续 Bash 聚合

- **WHEN** 工具序列为 Bash、Bash、thinking、Bash、Bash、Bash（thinking 显示开关关闭时）
- **THEN** 渲染为一个「执行 5 条命令」分组项，不因 thinking 断组

#### Scenario: 异类工具断组

- **WHEN** 工具序列为 Bash、Bash、Edit
- **THEN** 渲染为「执行 2 条命令」分组 + 1 个独立 Edit 卡片

#### Scenario: 编辑组内路径去重

- **WHEN** 连续 Edit/Write 共 5 次调用涉及 3 个不同文件路径
- **THEN** 分组项收起态展示 3 个去重路径，展开后仍可见全部 5 次调用

### Requirement: 工具卡片语义摘要

工具卡片收起态摘要 SHALL 优先取工具输入的 `description` 字段（agent 写的意图描述）；缺失时按工具类型回落：Bash 用 `command` 原文、文件类工具用 `file_path`/`path`，其余沿用既有 `summarize` 兜底。

摘要超长 MUST 截断省略（单行截断，不换行撑高）。

#### Scenario: 有 description 时优先语义摘要

- **WHEN** Bash 工具输入为 `{"command":"python3 bin/run_full_suite.py --baseline x","description":"跑全量回归对齐基线"}`
- **THEN** 卡片收起态摘要显示「跑全量回归对齐基线」，而非命令原文开头

#### Scenario: 无 description 时回落原文

- **WHEN** Bash 工具输入仅有 `{"command":"git status"}`
- **THEN** 卡片收起态摘要显示 `git status`

### Requirement: 工具耗时标注

系统 SHALL 利用 `tool_progress` 心跳事件（含 `parent_tool_use_id` 与 `elapsed_time_seconds`）计算各工具调用的已观测耗时，标注在对应工具卡片（或分组内条目）上，格式如「8m30s」。

同一 `tool_use_id` 多条心跳时取最大 `elapsed_time_seconds`。无心跳覆盖的工具（快速完成、无心跳产生）MUST NOT 显示耗时标注。聚合分组 MUST 在组内每条命令行上展示各自成败与耗时。

#### Scenario: 长命令显示耗时

- **WHEN** 某 Bash 调用（id=call_K）运行期间产生心跳 `elapsed_time_seconds` 最大值 510
- **THEN** 该卡片可见「8m30s」或等价格式耗时标注

#### Scenario: 无心跳工具不显示耗时

- **WHEN** 某 Read 调用从未产生 `tool_progress` 心跳
- **THEN** 该卡片不显示耗时标注

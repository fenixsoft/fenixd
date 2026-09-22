## Context

运行记录展示链路：run jsonl → `get_run_events`（`core/dashboard/data/runs.py:464`，已读全量文件并返回 `total_events`）→ 路由 `run_routes.py:83` → 前端 `getRunTail` → `ClaudeOutputPane`（tail=300，SSE 增量）→ `runEventsToChatMessages`（`runEvents.ts:72`）→ `groupConsecutiveTools`（`toolGrouping.ts:30`）→ `MessageItem`/`ToolCard`/`Reasoning` 渲染。

量化现状（2026-09-22 对 3 份已完成 spec run 流实测）：工具卡片 33%（Bash 占半数以上，planner run 达 88%）、thinking 折叠块 14-19%、零信息心跳行 ~10%（`[tool_progress]`×74、`[status]`×21、`[task_started]`×21…）、assistant 正文仅 6-10%；tail=300 只覆盖最大 run 的 20%，其中 46 条是心跳。

约束：事件 jsonl 落盘格式不可变更（正在写入的 run 与历史归档产物都要能读）；四个消费入口共享同一渲染管线，改一处全员生效；前端单测为零依赖 node:test 直载 .ts（`tests/sessionEvents.test.mjs` 模式）。

## Goals / Non-Goals

**Goals**

- 用户打开运行记录后，不滚动即可看到「agent 在干什么」的主线（正文 + 语义化聚合后的工具组），心跳/标签裸行消失。
- thinking 折叠头给出时长与内容预览；思考显示可开关，开关关闭不破坏工具聚合。
- 大 run 可向前翻页到达流的开头，且计数可见。

**Non-Goals**

- 不改 run jsonl 落盘格式与写侧（`agent_runner`）任何行为。
- 不做后端事件过滤/裁剪（静默是纯渲染侧行为，原始事件仍完整可查）。
- 不做跨 run 检索/全局搜索、不做 run_metrics token 数修复（另有 fix-run-latency-toolresult-parser-spec 立项）。
- 不引入前端构建链以外的新依赖（无状态管理库、无虚拟滚动库）。

## Decisions

### D1 纯读侧改造，事件分类表收敛在 runEvents.ts 单点

所有降噪/语义化/回填判定都在 `runEventsToChatMessages` 内完成，产出 `ChatMessage` 时把「静默」表达为不产出条目、把「回填」表达为修改既有条目字段，替代当前 `runEvents.ts:218-224` 的 `[label]` 兜底。
理由：四个消费入口共用该函数；写侧零改动。备选「后端过滤事件」被否——会破坏 SSE 增量与归档产物的一致性，且丢信息不可逆。

**事件分类表**（唯一权威口径，实现与单测对齐此表）：

| 类型 | 判定 | 处理 |
|---|---|---|
| `tool_progress` | 无条件 | 静默；但按 `parent_tool_use_id` 记录 `max(elapsed_time_seconds)` 供耗时标注 |
| `background_tasks_changed` / `commands_changed` / `run_metrics` / `init` | 无条件 | 静默 |
| `stderr` | `line` 含错误关键词（`error`、`Error`、`Traceback`、`failed`、`FATAL`、`refused`，大小写敏感词表固化在常量） | 命中→系统行；未命中→静默 |
| `hook_started` / `hook_response` | 无条件 | 静默 |
| `provider_marker` | 无条件 | 系统条：`模型路由 <model> @ <provider>（第 i/共 n 棒）`；字段缺失降级为「模型路由」 |
| `transient_retry` | 无条件 | 错误样式系统条：`网关瞬断（<reason>），<backoff_seconds>s 后第 <retry_number> 次重试：<error 摘要 80 字>` |
| `compact_boundary` | 无条件 | 系统条：`上下文压缩（<trigger>）：<pre_tokens> → <post_tokens> tokens` |
| `vcs_state_changed` | `kind=commit` | 系统条：`提交 <short_hash> @ <branch>`；其他 kind 静默 |
| `task_started` / `task_notification` | `tool_use_id` 能匹配已产出工具条目 | 回填该条目（started→`taskDescription`；notification→`taskStatus`/`taskSummary`），不产出行 |
| `task_started` / `task_notification` | 无匹配 | 系统条兜底（含 description/summary 摘要） |
| `superseded` / `turn_extension` | 无条件 | 静默（轮转/续期是框架内部心跳） |

现有 `session_ended` / `error` / `interrupted` / `cancelled` 分支保持不变（既有测试锚定）。

### D2 工具聚合：类型类映射 + 不可见项跳过，仍在 groupConsecutiveTools 内

`toolGrouping.ts` 增加工具→类映射（查阅/命令/编辑/其他），同类连续即可成组（组标题带类名与计数）；`rendersNothing` 从「仅隐藏 thinking」扩展为「一切被静默的消息」（`runEventsToChatMessages` 对静默项不产出条目后，此场景自然消失，该扩展仅为防御）。分组容器沿用 `ToolGroupContainer`。
编辑组收起态展示去重路径（保持首现顺序），展开态仍列全部调用。
理由：最小侵入，既有阈值 2 与断组语义不变。备选「按阶段聚类（探索/编辑/验证）」被否——需要全文语义判定，误分组代价高且不可测。

### D3 工具卡片摘要与耗时

`ToolCard.tsx` 的 `summarize` 优先取输入 `description`；耗时来自 D1 收集的 `max(elapsed_time_seconds)` 映射（`ChatMessage` 新增可选字段 `toolElapsedSeconds`），卡片右侧以 `XmYs` 格式渲染；分组内条目行展示各自成败（既有 `toolResult.isError`）与耗时。无映射值不渲染。
理由：心跳事件本来就随流到达，零额外请求。

### D4 thinking 时长与预览；开关默认关闭 + 无正文兜底

- 时长：thinking 所在 assistant 事件的 `timestamp` 与**流中下一个 assistant 事件**的 `timestamp` 差（秒，四舍五入，负值/缺失回退「已思考数秒」）。注：assistant/user 事件带 ISO timestamp（SDK 注入），system 类事件不带——只用 assistant 事件间差。
- 预览：thinking 文本首个非空行截断 ~40 字符。
- 开关：`ClaudeOutputPane` 内部 state + 头部 Switch，默认**关闭**（现状默认开启，属行为变更，理由：量化数据显示 thinking 占 14-19% 且恒为折叠态，开启只贡献「已思考数秒」噪声行并打断工具聚合）。无正文兜底在 `runEventsToChatMessages` 内实现：全流无非空 text 块时忽略 `showThinking=false`。原 `showThinking` prop 保留，四个消费方无需改动。
- `Reasoning.tsx` 折叠头文案改为「已思考 N 秒 · <预览>」；流式「思考中…」不变。

### D5 向前分页：后端加窗口参数，前端「加载更早」

- 后端 `get_run_events(project_root, run_id, tail=300, offset_from_end=0)`：返回 `events[len-tail-offset : len-offset]`（负索引安全钳制），既有字段（`status`/`total_events`/`error`）语义不变；`offset_from_end=0` 时行为与现状完全一致。路由 `run_routes.py` 透传 query 参数。
- 前端 `ClaudeOutputPane`：头部计数「显示尾部 N / 共 M 条事件」（N=已加载条数，M=`total_events`）+「加载更早事件」按钮，点击以 `offset_from_end=当前长度` 重拉并**前置拼接**（SSE 增量只追加尾部，互不冲突）；`已加载 ≥ total_events` 时按钮禁用。历史 SSE `reset` 分支语义不变。
- 批大小沿用 tail 默认 300。

## Risks / Trade-offs

- [静默误伤：未来新增事件类型被当成心跳吞掉] → 分类表显式枚举静默名单，未命中名单的结构化事件仍走「系统条」渲染（fail-open 显示而非 fail-close 吞掉）；名单外事件渲染为「系统事件（<type>）」占位条。
- [耗时估算不准（心跳间隔 30s，粒度粗）] → 标注为约数即可（用途是「一眼分辨长命令」）；无心跳不显示，不造数。
- [thinking 时长把 API 等待也算进「思考」] → 文案用「已思考 N 秒」而非「耗时 N 秒」，接受近似；仅作导航信号。
- [offset 窗口边界行截断语义] → `get_run_events` 全量解析后按事件序号切片（非字节偏移），无半行问题；`read_run_events_between`（SSE 增量）不动。
- [showThinking 默认值翻转影响 admin 弹窗等入口] → 兜底逻辑保证 deepseek 系全程无正文形态仍可见 thinking；四个消费方均未显式传该 prop（已核实），无隐藏依赖。
- [大 run 全量渲染性能] → 默认仍只渲染尾部 300 条；向前翻页是用户显式动作。分段加载天然限流，不引入虚拟滚动。

## Migration Plan

纯读侧改造，无数据迁移。部署顺序：合并即生效（dashboard 静态资源由主树 dist 实时服务，实现分支需完成 `npm run build` 产出 dist 变更一并合并）。回滚 = revert 前端提交，无残留状态。

## Testing

- 前端单测（node:test 直载 .ts，沿用 `tests/sessionEvents.test.mjs` 零依赖模式）：
  - `runStreamNoise.test.mjs`：事件分类表逐行锚定（静默名单/语义化文案/降级/回填/兜底/stderr 词表）；
  - `toolGrouping.test.mjs`（扩展既有）：同类聚合/异类断组/thinking 不断组/路径去重/阈值 2；
  - `thinkingScope.test.mjs`：时长估算（含缺失回退）/预览截断/开关与无正文兜底。
- 后端：`tests/test_dashboard_api.py` 补 `get_run_events` 窗口切片用例（offset=0 等价现状 / offset 中段 / offset 越界钳制 / total_events 不变 / status 判定不受窗口影响）。
- 手工冒烟：打开已归档大 run（impl-add-impl-ocr-parallel-lane a1）核对心跳消失、分组聚合、计数与翻页。

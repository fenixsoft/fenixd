# Spec Delta: hang-discrimination

## ADDED Requirements

### Requirement: 事件必须区分为「实质事件」与「心跳」，进度口径只用实质事件
活性快照 MUST 把 run 流中的事件分为两类并分别计数：
- **实质事件**：`assistant`（工具调用/文本）、`user`（tool_result）、`result` 等承载任务进展的事件；
- **心跳**：`tool_progress` 等仅表明「进程仍在等待/存活」的周期性事件（无时间戳、按 `elapsed_time_seconds` 递增）。

一切「是否在推进」的判定 MUST 以实质事件为依据。心跳 MUST NOT 计入「窗口内有新事件」的进度证据，MUST NOT 作为 `advancing` 的依据。

**背景（本案实证）**：`_liveness_snapshot` 现口径把无时间戳事件「按文件 mtime 在窗口内即计入 `events_in_window`」，而心跳每约 30s 写一条、mtime 恒新。本案挂起 run 的窗口内有 **349 条心跳 vs 130 条实质结果**，导致既有「窗口内零事件 → 直接判停滞」守卫被恒久打穿，判定 LLM 也据此判 `advancing`。

#### Scenario: 仅心跳流入的窗口不得判为推进
- **WHEN** 判定窗口内有大量新写入的事件，但这些事件全部为心跳（`tool_progress`），实质事件为零
- **THEN** 判定 MUST NOT 得出 `advancing`；MUST 按「窗口内无实质进展」处理

#### Scenario: 零实质事件触发既有停滞守卫
- **WHEN** 判定窗口内实质事件数为零（即使心跳持续写入）
- **THEN** 系统 MUST 走「窗口内零事件即判停滞」路径，MUST NOT 因心跳而使该守卫失效

#### Scenario: 实质事件正常推进
- **WHEN** 窗口内有持续的新工具调用与工具结果（实质事件）
- **THEN** 判定 MUST 允许结论为 `advancing`，续期行为与既有语义一致

### Requirement: 快照上报进度口径的分离计数
活性快照 MUST 分别上报 `substantive_events_in_window`（窗口内实质事件数）、`tool_completions_in_window`（窗口内完成的工具调用数，即 tool_result 数）、`heartbeats_in_window`（窗口内心跳数），并在证据摘要中同时呈现，使事后复盘可直接读出「有多少是真进展、多少只是心跳」。

#### Scenario: 证据摘要可区分进展与心跳
- **WHEN** 一次活性判定产生证据摘要
- **THEN** 摘要 MUST 同时给出实质事件数、工具完成数与心跳数，MUST NOT 只给一个混合的「事件数」

### Requirement: 停滞判定的确定性短路仅限「可观测零产出」情形，且必须留痕为启发式
当且仅当以下三者同时成立时，系统 MAY 走确定性短路直接判停滞（不经判定 LLM）：
1. 该 run 在窗口内**阻塞等待**某个后台调用（长时 `TaskOutput`/背景命令）不短于固化阈值；
2. 该后台调用关联的输出文件**可观测**，且其大小在窗口内**零增长**；
3. 窗口内 `tool_completions_in_window` 低于固化阈值。

短路判定 MUST 在 run jsonl 与 daemon 日志中标注为**启发式「零产出」判定**（与 LLM 判定、与其他短路原因在文案上可区分），并 MUST 记录被判定的后台调用标识与输出文件路径、观测到的零增长区间。任一条不成立（尤其输出文件不可观测）时，MUST 走既有 LLM 判定路径，MUST NOT 短路。

**背景（本案实证）**：挂起 run 的后台任务输出文件停在 0–22 字节而 Agent 轮询数小时（如 `b2393npxo.output`=0B、`beqdmo0dh.output`=22B），这是唯一真正反映「子进程挂起」的可观测信号。

**明确排除的判据**：MUST NOT 以「重复相同工具调用占比」或「工具结果文本重复度」作为停滞判据。本案实测二者均不判别——挂起 run 的调用重复占比 0.06–0.13、结果重复度 0.15–0.21，而合法长跑 run 的结果重复度反而更高（最高 0.24）；以 0.75 为阈永不触发，下调到能触发则误杀合法 run。

#### Scenario: 零产出短路成立
- **WHEN** 某 run 阻塞等待一个后台调用超过阈值，其输出文件可观测且窗口内大小零增长，且窗口内工具完成数低于阈值
- **THEN** 系统 MAY 直接判停滞并进入终止路径，MUST NOT 调用判定 LLM，且证据 MUST 标注为启发式「零产出」判定

#### Scenario: 输出文件不可观测时不得短路
- **WHEN** 上述条件中输出文件不可观测（无关联输出文件或不可读）
- **THEN** 系统 MUST 走既有 LLM 判定路径，MUST NOT 走零产出短路

#### Scenario: 重复调用形态不得作为判据
- **WHEN** 窗口内存在大量重复相同工具调用，但不存在「可观测零产出」的三条件组合
- **THEN** 系统 MUST NOT 仅凭重复占比判停滞，MUST 走既有判定路径

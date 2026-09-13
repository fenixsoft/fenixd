# Spec Delta: agent-run-timeout-supervision

## MODIFIED Requirements

### Requirement: Run 到达墙钟时限时先做活性评估，不得直接硬杀
agent run（implementer/tester 等）到达 `agents.run_timeout_seconds` 时，系统 MUST 先进入活性评估流程；仅当评估结论为「停滞」（含确定性短路判定的停滞）或后续受限条件触发时才允许终止进程。

#### Scenario: 到达时限且流仍在活动
- **WHEN** run 进程到达配置的墙钟时限，且其 run jsonl 在最近判定窗口内有新增事件
- **THEN** 系统 MUST 启动活性评估而不是立即 kill 进程，并在判定期间继续接收流输出

#### Scenario: 重复操作占比超阈时确定性短路
- **WHEN** run 到达墙钟时限，且判定窗口内重复相似操作占比已达固化阈值（见 hang-discrimination）
- **THEN** 系统 MUST 直接判为停滞并进入终止路径，MUST NOT 发起判定 LLM 调用

#### Scenario: 判定不可用时的失败安全
- **WHEN** 判定 LLM 调用失败（网络异常、网关拒绝）无法得出结论，且未触发确定性短路
- **THEN** 系统 MUST 回退为本次按停滞处理终止进程，并在日志与 run 文件中记录「liveness judge unavailable」

### Requirement: 活性判定基于运行证据并全程留痕
活性判定 MUST 以 run 流的可量化证据为输入（最近事件时间戳间隔、窗口内 tool_use 数量与类型分布、是否重复相似操作、等待中的后台子进程是否零产出），由独立于被判定 run 的 LLM 给出「advancing / stagnant」结论；其中「是否重复相似操作」为 MUST 输入，重复占比超阈值时 MUST 确定性判停滞而不经 LLM；每次评估与续期决策 MUST 写入 run 文件与 daemon 日志供审计。判定口径 MUST 明确：持续产出事件或 I/O 增长 MUST NOT 单独构成 `advancing` 的充分依据。

#### Scenario: 判定为仍在有效推进则续期
- **WHEN** 证据显示窗口内有持续的新工具调用、操作多样化且产出新内容，判定 LLM 结论为 advancing
- **THEN** 系统 MUST 将该 run 的时限延长 `agents.timeout_supervision.extension_seconds`，并向调度器广播续期事件使 stuck 检测的起始时间随之顺延

#### Scenario: 判定为停滞则携带证据硬杀
- **WHEN** 判定结论为停滞（包括 LLM 判定，或重复占比超阈的确定性短路）
- **THEN** 系统 MUST 立即终止该 run 并按现有失败路径处理，run 文件中 MUST 包含被判停滞的证据摘要（含重复指纹构成，若为短路判定）

#### Scenario: 事件增长不足以支撑 advancing
- **WHEN** 窗口内事件与 I/O 持续增长，但工具调用以同指纹重复为主
- **THEN** 判定结论 MUST NOT 为 advancing

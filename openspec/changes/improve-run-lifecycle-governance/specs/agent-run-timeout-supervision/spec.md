# Spec Delta: agent-run-timeout-supervision

## ADDED Requirements

### Requirement: Run 到达墙钟时限时先做活性评估，不得直接硬杀
agent run（implementer/tester 等）到达 `agents.run_timeout_seconds` 时，系统 MUST 先进入活性评估流程；仅当评估结论为「停滞」或后续受限条件触发时才允许终止进程。

#### Scenario: 到达时限且流仍在活动
- **WHEN** run 进程到达配置的墙钟时限，且其 run jsonl 在最近判定窗口内有新增事件
- **THEN** 系统 MUST 启动 LLM 活性判定而不是立即 kill 进程，并在判定期间继续接收流输出

#### Scenario: 判定不可用时的失败安全
- **WHEN** 判定 LLM 调用失败（网络异常、网关拒绝）无法得出结论
- **THEN** 系统 MUST 回退为本次按停滞处理终止进程，并在日志与 run 文件中记录「liveness judge unavailable」

### Requirement: 活性判定基于运行证据并全程留痕
活性判定 MUST 以 run 流的可量化证据为输入（最近事件时间戳间隔、窗口内 tool_use 数量与类型分布、是否重复相似操作），由独立于被判定 run 的 LLM 给出「advancing / stagnant」结论；每次评估与续期决策 MUST 写入 run 文件与 daemon 日志供审计。

#### Scenario: 判定为仍在有效推进则续期
- **WHEN** 证据显示窗口内有持续的新工具调用与新事件，判定 LLM 结论为 advancing
- **THEN** 系统 MUST 将该 run 的时限延长 `agents.timeout_supervision.extension_seconds`，并向调度器广播续期事件使 stuck 检测的起始时间随之顺延

#### Scenario: 判定为停滞则携带证据硬杀
- **WHEN** 判定 LLM 结合证据（如长时间零事件、或在同一环节反复出现相同错误输出）结论为 stagnant
- **THEN** 系统 MUST 立即终止该 run 并按现有失败路径处理，run 文件中 MUST 包含被判停滞的证据摘要

### Requirement: 续期受次数与绝对上限双重封顶
系统 MUST 对单个 run 的累计续期施加 `agents.timeout_supervision.max_extensions` 次数上限与 `agents.timeout_supervision.absolute_max_seconds` 总时长上限；任一封顶命中即不再评估、直接终止。

#### Scenario: 续期次数耗尽后不再评估
- **WHEN** 某 run 已连续完成 max_extensions 次续期并再次到达当前时限
- **THEN** 系统 MUST 直接终止该 run 并记录「extension budget exhausted」，跳过 LLM 判定

### Requirement: 功能可通过配置整体停用
`agents.timeout_supervision.enabled` 为 false 时系统 MUST 保持既有纯墙钟行为（到点硬杀）；相关配置键缺失时 MUST 使用文档化的默认值且不影响主流程。

#### Scenario: 停用后行为回归现状
- **WHEN** 配置中 timeout_supervision.enabled=false，run 到达墙钟时限
- **THEN** 系统 MUST 按 3600s 硬杀的现行行为处理，不发生任何 LLM 判定调用

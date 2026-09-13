# Spec Delta: run-budget-continuity

## ADDED Requirements

### Requirement: 同一 SPEC 的重试共享预算口径
同一 spec 因超时/被杀而产生的多次 attempt MUST 计入同一 spec 级预算口径（累计墙钟时长与累计续期次数），MUST NOT 让每次重派都获得一份全新的满额预算。spec 级累计预算耗尽时，spec MUST 进入可判定的终态（如 blocked 或 failed，沿用既有终态语义），MUST NOT 再次按满额重派。

判定依据 MUST 为 spec 级累计值（含此前所有 attempt 的墙钟消耗与续期消耗），派发新 attempt 时 MUST 先以该累计值扣减本次可用预算。

#### Scenario: 新 attempt 不重置为满额
- **WHEN** 某 spec 的前一个 attempt 已消耗墙钟 12600s（含 2 次续期）后被杀，框架重派新 attempt
- **THEN** 新 attempt 的可支配预算 MUST 按 spec 级累计扣减，MUST NOT 重新获得完整的 `run_timeout + max_extensions × extension_seconds`

#### Scenario: spec 级预算耗尽进入终态
- **WHEN** 某 spec 的累计预算（跨 attempt 求和）已达到 spec 级上限
- **THEN** 该 spec MUST 收口为可判定终态并记录预算耗尽归因，MUST NOT 继续派发新的满额 attempt

### Requirement: 重派 attempt 继承上一轮结构化诊断
重派新 attempt 时，系统 MUST 将上一轮 attempt 的结构化诊断摘要注入新 attempt 的 prompt 上下文，使新 attempt 不从零重复探测同一个阻塞。诊断摘要 MUST 为结构化字段（而非原始转录原文），至少包含：上一轮终态与归因（超时/被杀/失败）、上一轮已得出的定性结论（若已写入）、上一轮已提交的进度（分支与已勾选任务）。

无上一轮诊断（首个 attempt）时 MUST NOT 注入占位内容，行为与现状一致。

#### Scenario: 继承上轮诊断
- **WHEN** 前一 attempt 因超时被杀，且该 attempt 已在 run 文件中留下「全量套件在 32% 处挂起」的定性结论或等价归因
- **THEN** 新 attempt 的 prompt MUST 包含该结论，使新 attempt 可直接据此改变策略而非重跑同样的探测

#### Scenario: 首个 attempt 无继承
- **WHEN** 某 spec 的首次 attempt 被派发（无前置 attempt）
- **THEN** prompt MUST NOT 包含任何上一轮诊断段，其余行为与现状一致

### Requirement: 继承内容为结构化摘要且可审计
注入的诊断摘要 MUST 可被独立查看与审计（写入 run 文件或等价可读位置），MUST NOT 仅以临时字符串形式存在。摘要中 MUST NOT 包含上一轮 run 的完整转录原文（控制注入体积）。

#### Scenario: 摘要可审计且非转录原文
- **WHEN** 一次重派注入了上一轮诊断摘要
- **THEN** 该摘要 MUST 可在 run 文件或等价位置读取到，且其内容 MUST 为结构化字段而非上一轮转录原文的搬运

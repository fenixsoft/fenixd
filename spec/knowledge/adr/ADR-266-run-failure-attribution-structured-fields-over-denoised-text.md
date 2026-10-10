# ADR-266：run 失败归因以结构化字段传递，禁依赖降噪 stderr 文本

date: 2026-10-11
status: accepted

## Context

上游账户级 429 限流撞上批量评审窗口时，「这是限流」的信号在跨层传递中丢失：
runner 在异常上挂载 `exc.api_error_status`，但车道 run 包装器的 catch-all 将其
降级为 `error=str(e)` 纯文本；`AgentRunResult` 无结构化字段承载；stderr 经
降噪后只剩 `Exit code: 1`，失败分类的文本指纹匹配恒不命中。结果：限流被当
评审质量失败烧光尝试预算并冻结 4 个 spec，需人工处置解冻。code_review、
code_fix 车道此前已各自落过同型归因，但结果对象协议层没有统一承载。

## Decision

单轮 API 错误的归因（`api_error_status`、连接类标记 `conn_error`）作为
`AgentRunResult` 的结构化字段随结果对象传递；车道 run 包装器的 catch-all
负责从异常回填。失败分类入口优先消费结构化字段（429 / conn_error 命中即判
infra 类），降噪后的 stderr 文本指纹仅作结构化字段缺席时的回退。后续车道
的失败归因实现必须沿用「结果对象结构化字段优先、文本回退」的分层，不得以
stderr 文本匹配作为主判据——降噪策略与文本形态不是归因契约。

## Consequences

- 归因确定性不再受 stderr 降噪策略影响；命中结构化归因的供给瞬态直接流入
  既有 infra 分支（不烧尝试预算、熔断冷却自动恢复），零新增车道结构。
- `AgentRunResult` 增可选字段对既有构造方兼容（不传即缺省）；文本指纹词表
  仍需维护，作为存量无结构化归因路径的兜底。
- 异常挂载点与结果对象字段构成两跳传递链，新增归因维度时需同时覆盖挂载侧
  与消费侧，缺一侧即静默回落文本回退。

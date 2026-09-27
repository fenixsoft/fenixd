# ADR-004：Provider 失效转移以 attempt 边界推进

date: 2026-09-02
status: accepted

## Context

agent 角色的 provider 可配置为按序候选链。两家 provider 同窗口分别以 `unrecognized_model` 拒绝全部请求的事故表明：静态单 provider 分配在 provider 侧故障时无路可走，而既有熔断只能「抑制派发」，没有「换一家继续」的路径。需要裁定切换发生在什么粒度、由什么错误驱动、以及切换后上下文如何处置。

## Decision

- 切换粒度为 attempt 边界：链指针只在 attempt 之间推进，进行中的进程不迁移、不做流中切换。
- 错误分类驱动链前进：`unrecognized_model` 文本、HTTP 5xx、连接异常三类判为切换类错误；配额/鉴权类 4xx 维持既有熔断语义，不驱动切换。
- 链级冷却与 4xx 熔断共用存储但键隔离（独立的 switch 冷却字段与阈值，默认 300s）；链选择跳过冷却未到期者，全链皆冷却时按失败返回，不无限打转；冷却到期后主链自动复位优先。
- 切换 provider 时照常携带 `--resume` 复用原会话：CLI 会话历史在本地、消息 API 无状态，跨端点 resume 上下文零损失；不做事前能力预检，切换事件落日志供审计。
- 每次 attempt 的 provider/model 落盘可查（run 产物 provider_marker 行 + `provider_used`/`model_used` 结果字段）；单 provider 当日 attempt 计数超阈值打 WARNING。

## Consequences

- provider 侧故障不再搁浅整条链，常态零开销（仅在主链失败时切换）；备份 provider 更贵的风险由每日计数告警兜底。
- 流中切换被明确放弃：已产出上下文与工作树状态不因切换而弃置。
- 切换类错误的文本匹配对新报错形态可能漏判——分类只触发「链前进 + 短冷却」，不永久拉黑，漏判的代价有界。

# ADR-124：run 流转录 tool_result 识别单一真源

date: 2026-09-18
status: accepted

## Context

延迟观测与 turn-limit 流量活性两条能力独立硬编码「顶层 `tool_result` 事件」，而 claude stream-json 从不产生顶层 tool_result——工具结果一律由 `user` 事件包裹在 `message.content` 中。多条消费点恒盲（延迟样本恒空、流量活性恒 False），测试用与生产相同的错误前提构造合成事件自我证明，未能拦住。

## Decision

- 转录事件形态识别收敛到单一共享判定函数，全部消费点调用；识别语义为「user 事件包裹 tool_result block ∪ 顶层 tool_result 兼容分支」，user 的 content 为字符串或纯 text block 时不识别（杜绝假样本）。
- 配对口径不变：一个 user 事件承载 N 个 tool_result block 仍算一次 API 往返样本。
- 消费 run 流转录的新能力禁止各自假设事件形态；解析器失明自检（有 assistant 事件却零样本）输出 WARNING 日志（不入人工告警），失明与「真空跑」以 turn_count 区分。
- 涉及外部格式契约的解析必须有真实形态夹具，禁合成 schema 自我证明。

## Consequences

- 转录格式再变时单点修正；流量活性从恒 False 恢复为真实证据（turn-limit 续期矩阵结构与其余常量不变，ADR-103 口径不受影响）。

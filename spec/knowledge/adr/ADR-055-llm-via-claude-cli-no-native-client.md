# ADR-055：LLM 能力借道 claude CLI，框架不实现独立 LLM 客户端

date: 2026-09-09
status: superseded
Superseded by: ADR-271(pluggable-agent-harness)

## Context

dashboard/daemon 侧陆续出现轻量 LLM 生成需求（如项目简介生成），存在「自研 Python LLM HTTP 客户端」与「复用既有 claude CLI」两条路。新项目初始化时 provider 常未配置，自研客户端大概率走兜底且引入新的依赖与凭据维护面。

## Decision

- 框架不实现独立 LLM 客户端、不为此新增脚本依赖：交互式场景（setup / skill 流程）由执行会话自身完成生成；后台场景（dashboard / daemon）统一 headless `claude -p`。
- headless 调用纪律：参数列表传递（文档内容不经 shell，无注入面）、cwd 锚定项目根、超时有界、继承 daemon 环境（走既有网关路由）；失败（非零退出/超时/空输出）返回错误、不改原值、不阻塞任何流程。

## Consequences

- LLM 路由、凭据、failover 全部继承既有 CLI/网关语义，零新增维护面；后续任何轻量生成需求沿用此模式，不得另起 HTTP 客户端。
- 代价是无流式与结构化输出控制，只适合一句话级产物；重 LLM 职责仍归 agent 车道。

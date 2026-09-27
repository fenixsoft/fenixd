# ADR-039：v2 数据分层——字段逻辑收口 Adapters 纯函数层，页面 JSON 不做字段逻辑

date: 2026-09-05
status: accepted

## Context

API 字段存在历史坑：verdict.summary 计数可能是字符串 "0"；GET /api/config 无 llm 键时结构缺失；数字字段有「空/NaN」漂移。AMIS 页面 JSON 内嵌字段逻辑不可单测、不可跨页复用。

## Decision

- `window.Adapters`（UMD 双出口 `module.exports`/`window`，node:test 与浏览器共用一份代码）是全部字段逻辑的唯一收口：adaptSpecs/adaptOverview/adaptConfig 等均为纯函数，零 API 请求、不碰 SSE；页面 JSON 的 service adaptor 只调用 Adapters，自身不做字段逻辑。
- 计数字段一律 `Number()` 归一（NaN→0），数字字段按「空/NaN → 已加载快照 → 领域默认」三级回退；字段名以 behavior.md 字段表为逐字权威，Adapters 负责结构缺失兜底。
- 页面间共享的数据规则（fix-<父名> 归入父行 children、SPEC 按生命周期序排序）在 Adapters 内实现，页面只渲染。

## Consequences

- 字段逻辑可用 node 单测贴真实响应 fixture（curl 现网端点采样）覆盖；页面 JSON 保持纯声明。
- 后续页面 SPEC 新增字段逻辑必须进 Adapters 层，不得写入页面 JSON——这是对全部后续页面 SPEC 的硬约束。

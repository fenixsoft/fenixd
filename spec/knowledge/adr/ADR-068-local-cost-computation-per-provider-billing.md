# ADR-068：成本金额只认本地计算，价格配置内嵌 provider、计价归属以实际生效网关为准

date: 2026-09-11
status: accepted

## Context

网关普遍不回传 `cost_usd`，依赖网关回传的金额展示长期「成本不可用」；而 run 产物已留痕 usage 与实际生效的 provider/model（failover 后的真相）。成本需要一个不伪造、可回溯历史的计算口径与存放结构。

## Decision

- **只认本地计算**：读侧从 run 产物解析 usage 与 provider marker 现算金额，不新增持久化、不改 runner——历史 run 与归档 run 立即可算。
- **价格配置内嵌 provider 对象**：`llm.providers[i].billing = {enabled, prices: [{model, 输入/输出/缓存读/缓存写四价}]}`；计价闸门为 per-provider 谓词（卡片开启 + 行 model 精确匹配），未开启/未匹配不下发成本字段。不设顶层独立计费段与全局开关。
- **四价齐备才有效**：缺项宁可该 run 整体不可计价（None），不静默低估——「金额展示不伪造」优先于覆盖率。
- **计价归属以 run 产物 marker 为准**（failover 实际生效的网关与模型），非配置首选。
- 成本仅为展示口径：STATE token 累计、预算告警链路不动；按当前配置现算即「按现价重估」，不做历史成交价快照。

## Consequences

- 价格行拼写错误表现为规模可见的「N 个未计价 run」附注，而非错误数字。
- 同 spec 前后 run 单价可能随改价不一致（口径明示为现价重估）；删除 provider 卡片时价格随删无孤儿。

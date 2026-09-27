# ADR-127：失败三态归类 product/infra/env，门禁计数只认 product

date: 2026-09-21
status: accepted

## Context

验证失败归因最初只有「是否 infra」一个 bool：provider 抖动、环境问题与产品缺陷压进同一计数器——infra 轮消耗实现预算、累计失败轮次、把 spec 推向冻结。而把该 bool 函数原地改成三态返回值会让 `if is_infra(...)` 在字符串返回值下恒为 truthy，legacy infra 门全线失效——分类扩展与既有消费点签名是耦合的。

## Decision

- 失败三态 `product | infra | env`，以独立新函数承载分类，既有 bool 判定函数签名不变（legacy 消费点按 bool 语义继续成立）。
- 门禁阈值（失败轮次、冻结）只累计 product 失败；infra 轮次只做观测记账，不参与任何冻结阈值。
- infra 轮次的预算豁免沿用事后补偿范式（预算在 run 启动时计数、分类在收尾才可知，不做计数时点感知），且补偿必须纳入对账豁免集合——否则对账会按正常收工数回写 `used`，把退款冲掉。
- env 失败维持既有专用 blocked 通道与轮次阈值，infra 归类只在其上补记账与退款，不改其语义（「env 失败绝不放行」是刻意设计）。
- unknown（无法归类）保守按 product 处置：不豁免、照常计数。宁可少豁免，不可误豁免——误豁免绕过预算闸门并掩盖真实失败计数。
- 分类台账仅作策略生效后轮次的审计参考，不作为回拨的强制依赖（台账会被升级冻结与 verified 终态清空；历史轮次回拨以人工核验 run 产物为准）。

## Consequences

- dashboard 可展示 infra 与 product 的失败构成占比；infra 轮不再误伤预算与冻结阈值。
- 分类函数挂在统一归因入口，任何新增失败通道必须声明其三态归属并接入同一记账分层。

# ADR-317：全局政策拍板只归 Arbiter，Admin 超范围走结构化转单

date: 2026-11-03
status: accepted

## Context

处置链两级车道视野不同：Admin 是受限环境运维（受限工具、只见当前 run 注入结果），Arbiter 持全局视野。预算/豁免类信号（如 impl 预算耗尽）超出 Admin 运维面，历史上「预算政策 MUST 只产裁决包」把这类信号全部推向人工；同时 Admin 处置需要表达「超出我的范围」时，若重载 `result=escalate`（语义为「需人工决策」）会破坏既有消费者。

## Decision

自动化拍板权限按视野分级：

- 全局政策类拍板（预算 override、豁免类字段写入）只归 Arbiter 拍板动作面——写 spec 预算 override 字段（`impl_run_budget_override` 等既有字段复用）并落台账留痕；「预算政策只产裁决包」的旧限制就此解除；
- Admin choices 白名单不含预算/豁免类——受限视野不拍全局政策；Admin 判定超出运维面时以结构化产出 `handoff: "arbiter"` + `handoff_reason` 转单，直达 Arbiter 单飞队列，不重载 `result=escalate` 既有语义（「需人工决策」的消费者零破坏），转单不计 Admin 失败。

后续扩展任一车道动作面时须守住「受限视野不拍全局政策」分界；越界动作一律走结构化转单，禁止横向扩权或复用既有结果字段承载新语义，改动须显式 supersede。

## Consequences

预算政策类信号获得全自动化闭环通道（不再一概推向人工）。Admin 转单边成为链内常规路径，Arbiter 承接全部全局裁量负载，其拍板面与台账留痕是政策类变更的唯一自动化入口。`result=escalate` 语义保持稳定，旧消费者零改动。

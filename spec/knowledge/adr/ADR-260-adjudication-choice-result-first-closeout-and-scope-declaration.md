# ADR-260：裁决 choice 作用域声明注册表化 + 执行结果前置守终态

date: 2026-10-09
status: accepted

## Context

处置消费链的终态回写先于 choice 执行：全局信号（spec 为空或被占位符 'global' 顶替，如 daemon_errors 类无 spec 归属信号）选到 spec 作用域动作（retry_review 等）时，信号在同秒已被回写 handled=true / result=resolved，choice 执行其后再报「spec not found」且不阻塞收尾——告警记录 action_taken 与 result 恒为 null，信号被假闭环、永无重审入口。「全局信号 × spec 作用域 choice」是无路由防护的组合缺口，自动处置与人工下拉双通道同面；未注册 signal_type 还存在跨信号全表反查兜底放行，使 spec 作用域动作对无 spec 可操作的信号可达。

## Decision

- choice 作用域在注册表逐项显式声明（`spec_scoped` 字段，缺省按 True 保守处理），执行器与消费端据此守卫，禁硬编码动作清单；spec_scoped 动作对未注册 signal_type 禁全表反查兜底放行，非作用域动作保留反查可达。
- 双层设防：消费端对全局信号的 spec_scoped choice 提前跳过并留 INFO（避免无谓报错），执行器拒绝是正确性底线；两层共用注册表同一解析单源防漂移。
- 处置终态回写结果前置：choice 执行结果并入终态判定——成功才回写 handled/resolved，失败（含守卫拒绝与非法 choice_id）记 result=failed、action_taken 留动作名、处置记录 error 留因，信号保留待重审；留痕与 handled 置位必须解耦（可只留痕不闭环，缺省调用向后兼容）。
- 全局信号必须保留至少一个非作用域等价动作（ack_self_heal 类）保证执行收口不断路；呈现侧不做作用域过滤，守卫职责在执行时兜底。

## Consequences

- 失败信号保留待重审、可重入处置，处置记录自带失败原因可审计，假闭环通道关闭；人工端点既有「失败不标记 handled」防护与自动通道收敛为同一执行器同一纪律。
- 后续新增 choice 必须声明作用域（漏声明的 spec_scoped 动作对全局信号不可执行），新增或改动处置回写路径必须沿用结果前置与留痕解耦；全局形态信号的已注册桶须至少含一个非作用域选项，否则该桶在全局信号下永远无法执行。

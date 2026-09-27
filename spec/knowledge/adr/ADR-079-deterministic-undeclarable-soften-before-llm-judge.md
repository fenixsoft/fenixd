# ADR-079：确定性不可交付声明机械软化，LLM 终审只接语义矛盾

date: 2026-09-13
status: accepted

## Context

声明段四类不可交付模式——dist 构建产物、gitignored 路径、`~` 仓库外路径、`.fenix/` 运行时文件——原理上不可能经 merge-back 交付，且全部可用确定性信号判定（`git check-ignore` 原生判定、路径解析前缀判定）。此前它们与真正的语义矛盾混在同一通道：每例「1 次晋升返工 + 1 次 admin 往返」，守卫缺件一律进 dispute-judge LLM 终审烧钱。

## Decision

- 处置分级：可机械判定的不可交付模式在一切 LLM/人工介入之前机械软化——声明条目 kind 改写为 `reference`（软化终点，`reference` 恒不再软化）；LLM 终审只接语义矛盾；人工只接 judge 不决。
- 晋升期：软化永远先于 lint，保证确定性模式不产生 drafted+error 卡死；守卫期：judge 派发前预分类，命中条目直接软化并重跑守卫，全清即放行不派 judge，剩余项才进 LLM 终审。
- 产出期同步教学：schema instruction 与 fenix-new 指引注入同表四类模式，把修正知识前移到起草时。
- 审计与兜底：软化全程 dispute 审计留痕（verdicts[].reasoning 前缀区分 promotion-soften / guard-preclassify，不扩 schema）；单条改写异常跳过该条交由 lint 兜底（fail-safe），分类器判定异常不软化（fail-open，lint 照旧拒绝）。
- 防洗白边界：软化只针对「本就无法交付」的模式，真缺件仍被守卫拦截（重跑闸门），lint 规则 1-4（占位符/目录/不存在/疑似笔误）语义不动——它们需 path 修正，软化会掩盖真错。

## Consequences

- 确定性缺陷的「晋升返工 + admin 往返」代价归零；LLM judge 的触发面收窄到纯语义矛盾。
- 分类器零语义推断（只认 gitignored 与仓库外两个确定性信号），误判面极小；「gitignored 却声明 new」这类声明自身矛盾被显式化审计而非静默放行。

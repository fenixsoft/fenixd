# ADR-117：delete 交付物 kind——一等硬契约且豁免一切机械软化

date: 2026-09-19
status: accepted

## Context

Deliverables 声明只有 new/modify/reference 三类，「删除文件」没有可用形态：声明 modify 会被收工守卫按实现分支存在性确定性误判缺件（打回循环）；声明 reference 则晋升与守卫都不校验——既有事故中三项任务全勾、spec 已 pushed，删除目标原封不动。同时框架存在两条把「确定性不可交付」声明机械软化为 reference 的自动化（晋升期与守卫期）：软化对 new/modify 是止血，对 delete 恰好把「该删」降级成「仅审计」。

## Decision

- 新增声明 kind `delete`，语义「合并后该路径不存在」，归入 deliverables 硬校验桶（复用既有 dispute→LLM 终审→重派处置链，不新开第三桶）；守卫返回结构由字符串清单改为携带 kind 的结构化条目——「该删的还在」不得被表述成「缺件」。
- `delete` 只允许入库文件：gitignored 路径上的 delete 在晋升 lint 直接拒绝。守卫判定基准是实现分支 blob，gitignored 路径不属于任何分支、恒判通过，等于给空跑发永久绿灯；「运行时文件删除」须在立项当下暴露（交付方式：不进 Deliverables 段，人工在主树执行）。
- `delete` 排除出全部软化路径（晋升软化、守卫确定性预分类、LLM 终审的 reference 归宿，三处缺一即复刻原缺陷）：对 delete 而言软化在语义上就是错，应当升级人工而非自动降级；LLM 对 delete 条目的合法归宿收窄为 typo/missing/unclear，判 reference 时机械拒绝并转人工。

## Consequences

- 「声明了删除」与「删除真的发生」之间有了机械凭证；两类违规（该删的还在 / 该建的不在）共用同一处置链与同一份审计。
- 残余风险如实承认：作者仍可用合法组合 `reference`+gitignored 表达删除意图，文本匹配不可靠，只做教学劝阻，不假装已闭合。

# ADR-236：API 超时现场抢救挂失败当时，接续走 reuse 认领禁 consume_legacy

date: 2026-10-06
status: accepted

## Context

code-fix 批 run 死于一次单轮 API 请求超时（CLI 合成 "Request timed out" → Exit 1）即整轮判失败，且既有机制全部接不住该签名：车道无重试通路、停滞判停覆盖不了 1/95 样本的慢死（且缺省关闭）、Pre-rmtree 快照产生于失败约 2 小时后的陈旧清扫期——彼时消化链已推进多批，快照注定成为全仓无读者的悬空 commit。实测 316 turns / 约 43 分钟 / 10 美元级工作净损失。

## Decision

三段裁定，约束后续一切触碰该签名的实现：(1) 签名判别收口 agent runner 层一次完成（末次 result `terminal_reason=="api_error"` 或 result 文本命中超时文本），车道层只读结构化布尔标记，禁编排层重复解析归档二次判别；(2) 现场抢救挂在失败判定的当时——命中签名且工作区脏即 salvage 提交落批分支 + recovery legacy 保全 + 置复用标记，不依赖也不后移到清扫期（清扫期快照防线仅保留为最后防线）；(3) 同链接续只走 reuse 认领（`mark_legacy_reusable` + create 既有 `_take_reusable_worktree`，认领不可用 fail-open 全新建树），MUST NOT 调 `consume_legacy` 做接续——其回收语义（出册 + 强删 worktree + 删分支）会删掉承载 salvaged 提交的分支，复刻本决策要消灭的悬空净损失。非该签名的失败行为保形，不借机扩大 salvage 面。

## Consequences

签名复发即免于整批工作蒸发，接续端零新增机制（create 既有认领通路）。代价：salvaged 分支上的重复修复成本靠台账核销去重兜底（条目保持 open 不预核销）；认领与建树的竞态靠 fail-open 兜住——降级为全新建树时损失 salvaged 现场但不阻断链推进；抢救链路对签名判别的假阳性敏感（误标会把确定性失败也保全下来），故判别条件保持两形态窄口径。

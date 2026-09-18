# Proposal: spec-concurrency-flight-guard

## 问题

同一 spec 的并发 run（spec-review 与 implementer）无在飞互斥：spec-review run 收尾时按评审结论把刚进入 implementing 的 spec 回退为 ready（implementing→ready 合法、但未检查在飞实现 run），实现 run 在此基础上继续运行到合并，合并完成推进 implemented 时被转移表拒绝（ready→implemented 非法），产生 ERROR 噪音与 83 分钟状态矛盾（fix-start-after-premature-pickup 实证）。

## 证据

- fenixd.log：16:29:24Z ready→implementing 派发 implementer（impl-fix-start-after-premature-pickup-1789748964-a1）→ 16:30:16Z review 收尾 implementing→ready（repaired）→ 17:52:30Z ERROR Invalid transition ready→implemented
- core/state_machine.py:154-156：READY→仅[IMPLEMENTING]，ready→implemented 非法
- core/pm_engine/spec_review.py:283：收口（approved/repaired→回退）无 implementing 守卫
- 派发入口（engine.py _on_spec_ready）无在飞 reviewer 校验

## 设计思路

1. **审核收尾回退守卫**：spec-review 收口（回退到 ready/reviewing 前）重读 spec 当前 status——已 implementing（存在在飞实现 run）则跳过回退、仅记录 in-flight 日志；幂等（已非 implementing 零操作）。
2. **派发前在飞评审校验**：_on_spec_ready 派发 implementer 前检查同 spec 是否存在在飞 spec-review/repair run（审查状态/运行记录）；有则顺延派发（等 review 收尾后重判）。
3. **合并收尾 ready 态兜底**：实现 run 合并完成后状态推进时，若 spec 当前 status=ready 且该合并属实现 run 产物（携带通过评审证据）→ 自动补记 implementing→implemented（先合法转移再推进），消除 ready→implemented 非法转移 ERROR；非实现合并不触发。

## 范围

- 覆盖 spec 级并发 run（review/repair/implementer/verifier）的状态一致性
- 不覆盖跨 spec 并发（不同 spec 之间本无状态冲突）
- 与 fix-start-after-premature-pickup（start_after 派发门控）互补不重叠
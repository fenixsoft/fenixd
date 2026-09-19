# Proposal: spec-concurrency-flight-guard

## 问题

同一 spec 的并发 run（spec-review 与 implementer）无在飞互斥：spec-review run 收尾时按评审结论把刚进入 implementing 的 spec 回退为 ready（implementing→ready 合法、但未检查在飞实现 run），实现 run 在此基础上继续运行到合并，合并完成推进 implemented 时被转移表拒绝（ready→implemented 非法），产生 ERROR 噪音与 83 分钟状态矛盾（fix-start-after-premature-pickup 实证）。

并发面补充（自动路径的既有互斥，本 SPEC 不变）：自动侧「reviewing 才派 review、ready 才派 implementer」互不相交；run 终止后的重派（修复/零变更/交付物守卫等）在**同线程内**入队，`_enqueue` 的 `(spec, agent_type)` 去重（queue.py:71-73）吸收重复入队。故本 SPEC 治理的不是「自动评测同时跑」，而是**在飞/残留的评审 run 收尾时改写已被实现 run 接管的 spec 状态**，以及由此产生的 ready 态残留对后续派发与合并收尾的连带影响（阶段 2/3）。

## 证据

- fenixd.log：16:29:24Z ready→implementing 派发 implementer（impl-fix-start-after-premature-pickup-1789748964-a1）→ 16:30:16Z review 收尾 implementing→ready（repaired）→ 17:52:30Z ERROR Invalid transition ready→implemented（.fenix/logs/fenixd.log:41899 / :41926 / :42670）
- 连带证据：实现 run 合并于 17:52:30Z 被拒（.fenix/logs/fenixd.log:42670），spec 滞留 ready 直至 18:14:52Z 才被重新派发（:42905），18:39:24Z 第二次实现 run 合并成功（:43072）——同一实现工作被重做一轮。
- 同窗前序：15:59:11Z 首轮评审收尾 reviewing→ready（:41556），16:08:51Z 同一 spec 的评审 run 在 ready 态被再次派发（:41678，紧随其后更新 `reviewer_run`），16:25:23Z–16:28:26Z 事件总线对 ready 态孤儿该 spec 连发 4 次重派（:41835 起，每分钟一条）——ready 残留会把同一 spec 拉进重复派发面。
- core/state_machine.py:147-153：READY→仅[IMPLEMENTING]，ready→implemented 非法
- core/pm_engine/spec_review.py:285：收口（approved/repaired→回退）无 implementing 守卫
- 派发入口（engine.py _on_spec_ready :529 → `_enqueue` :628）无在飞 reviewer 校验；绕过它的直入队列路径（family.py:585、adjudication.py:1408、queue.py:870）同样无校验

## 设计思路

1. **审核收尾回退守卫**：spec-review 收口（回退到 ready/reviewing 前）重读 spec 当前 status——已 implementing/implemented/testing（存在在飞实现 run）则跳过回退、清 `reviewer_run` 锚点、仅记录 in-flight 审计侧车与 INFO 日志；幂等（其余状态零行为变化）。
2. **派发前在飞评审校验**：派发 implementer/fast-track 前检查同 spec 是否存在在飞 spec-review run（`reviewer_run` + 进程表/流文件分层判定，见 design D0）；有则顺延派发（等 review 收尾后重判）。落点两处（`_on_spec_ready` + dispatch 队列候选筛选）同口径，覆盖绕过前者的直入队列路径；陈旧锚点（run 已终态）判为无在飞评审并放行，防自造死锁。
3. **合并收尾 ready 态兜底**：实现 run 合并完成后状态推进时，若 spec 当前 status=ready 且该合并属实现 run 产物（调用点即实现合并收尾，三条落点：implementer/repair/fast-track）→ 自动补记 ready→implementing（合法转移）再推进 implemented，消除 ready→implemented 非法转移 ERROR；非实现合并不触发。

## 范围

- 覆盖 spec 级并发 run（review/repair/implementer/fast-track）的状态一致性
- 不覆盖跨 spec 并发（不同 spec 之间本无状态冲突）
- 与 fix-start-after-premature-pickup（start_after 派发门控）互补不重叠：该 SPEC 在其 5.2
  登记中已声明「绕过 handler 的直调通道」为已知缺口并建议后续 SPEC 治理，本 SPEC 的
  Requirement 2 落点两处（engine + dispatch 队列）即承接该建议的派发侧面对应部分
- 不改变自动路径既有互斥（`_enqueue` 的 `(spec, agent_type)` 去重、review 仅 reviewing 派发）

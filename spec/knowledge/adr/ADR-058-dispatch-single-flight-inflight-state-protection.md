# ADR-058：派发单飞守卫与在飞态保护——失败回写不降级活跃验证，验证结果不丢

date: 2026-09-09
status: accepted

## Context

daemon 启动时启动扫描与事件重放两条派发路径都能通过既有 worktree 守卫、在锁注册前的窗口内对同一 spec 双派发。同时两类竞态被实证：merge-back 失败回写 ready 会覆写已进入 testing 的在飞验证；verifier 完成时 spec 状态已被竞态改变，验证结果面临无处落地。

## Decision

- 派发单飞：进程内 pending 注册表在一切异步操作（含 worktree 锁创建）之前原子查重并置位，派发完成（成功或失败）清除；同一 spec 任意时刻至多一个在途派发意图，启动窗口被封死。
- 失败回写保护：merge-back 失败回写 ready 前，若 spec 已在 testing/implemented 且存在活跃 tester run，不降级状态——只记录冲突与熔断指纹，待验证结束后统一处置；在飞验证态不可被迟到的失败回写覆写。
- 验证结果对账：verifier 终态落地前核对当前状态，状态已被竞态改变时按当前态重放合法转换路径保结果落地（如 implemented → testing → bug-found）；无法重放则 blocked 并附证据，绝不静默丢弃验证结果。

## Consequences

- 状态机并发不变量成型：在飞工作不可被降级、已产出的裁决必须找到落点；与假成功防御（ADR-017）同族，共同构成终态可信边界。
- 单飞守卫为进程内存态，daemon 重启即清空——跨重启的重复派发防护仍由持久层守卫（worktree 锁、派发拦截）承担，两层缺一不可。

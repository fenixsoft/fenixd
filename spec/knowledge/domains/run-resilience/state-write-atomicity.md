<!-- knowledge: capability=state-write-atomicity rev=1 sources=spec/archive/2026-09-25-fix-state-atomicity-and-selfheal-restart -->

# 状态写入原子性

STATE.md 的并发一致性：写入以文件锁串行化并原子替换落盘，并发读者任一时刻只见完整旧值或完整新值，已提交的字段改动不丢失。

## 现行规则

- `StateMachine` 对 `.fenix/STATE.md` 的「读 → 改 → 写」在单次文件锁（`.STATE.md.lock`，`flock(LOCK_EX)`）内完成；锁为跨进程文件锁，不依赖进程内单例锁，daemon 与 dashboard 等各自持有独立 `StateMachine` 实例的进程并发写同一 spec 互不覆盖。
- 并发更新同一 spec 的不同字段均保留：任一已提交写入的字段改动不得被持陈旧快照的并发写入覆盖回旧值（如并发派发评审时各 spec 的 `reviewer_run` 保留本次派发的 run_id，不被清为 null，否则 `consume_review_result` 早退、评审结果永不消费）。
- 写入必留痕：任一路径修改 STATE.md 字段均产生可观测日志（含 spec 名与所改字段），不存在无日志的静默写入路径；凡会写 STATE.md 的 `StateMachine` 构造点必须注入真实 logger（构造器在 logger=None 时兜底为静默日志器，故仅改状态机本体不满足跨进程写入者的留痕要求）。
- 冻结 error 可靠持久化：`freeze_for_human` / `freeze_spec` 写入的 `error`（内嵌「原状态 X」子串，是 `parse_orig_status` 解析解冻目标的唯一来源）持续存在于 STATE.md 直至该 spec 被解冻；解冻时读出真实原状态并恢复之（原状态 reviewing 的冻结 spec 解冻后回到 reviewing，不回退 ready）。

## 溯源

- 史前复原 — 迁移期基线：STATE.md 写入以 fcntl 文件锁串行化并原子替换落盘，并发读者任一时刻只见完整旧值或完整新值
- [2026-09-25 fix-state-atomicity-and-selfheal-restart](spec/archive/2026-09-25-fix-state-atomicity-and-selfheal-restart/) — update_spec 的读改写收进同一把 .STATE.md.lock 消除并发丢失更新；确立写入必留痕与全部构造点真实 logger 注入；冻结 error 在并发下可靠存续、解冻恢复真实原状态

## ADDED Requirements

### Requirement: STATE.md 写入的原子性（无丢失更新）

`StateMachine` 对 `.fenix/STATE.md` 的「读 → 改 → 写」MUST 在单次文件锁（`.STATE.md.lock`，`flock(LOCK_EX)`）内完成。并发的多个写入 MUST NOT 因各自持有陈旧快照而互相覆盖——任一已提交写入的字段改动 MUST NOT 丢失。

#### Scenario: 并发更新不同字段均保留

- **WHEN** 两条写入路径并发地对同一 spec 的不同字段执行更新（如 A 写 `reviewer_run`、B 写 `error`）
- **THEN** 最终 STATE.md 中两个字段的改动 MUST 同时存在，MUST NOT 有任一被覆盖回旧值

#### Scenario: 评审派发写入的 reviewer_run 不被并发覆盖

- **WHEN** daemon 并发派发多个 spec 的评审 run 并分别写入各自 `reviewer_run`
- **THEN** 每个 spec 的 `reviewer_run` MUST 保留本次派发的 run_id，MUST NOT 出现被清为 `null`（否则 `consume_review_result` 早退、评审结果永不消费）

#### Scenario: STATE.md 写入必留痕

- **WHEN** 任一路径修改 STATE.md 中某 spec 的字段
- **THEN** MUST 产生对应的可观测日志（含 spec 名与所改字段），MUST NOT 存在无日志的静默写入路径

### Requirement: 冻结 error 的可靠持久化

`freeze_for_human` / `freeze_spec` 写入的 `error`（内嵌「原状态 X」子串，是 `parse_orig_status` 解析解冻目标的唯一来源）MUST 持续存在于 STATE.md 直至该 spec 被解冻；解冻时 MUST 能读出真实原状态。

#### Scenario: 冻结后并发写入不清除 error

- **WHEN** 某 spec 被冻结（`error` 含「原状态 reviewing」）之后，系统发生任意并发的 STATE.md 写入
- **THEN** 该 spec 的 `error` MUST 仍可被读取，`parse_orig_status` MUST 返回 `reviewing`

#### Scenario: 解冻恢复原状态而非回退 ready

- **WHEN** 一个「原状态 reviewing」的冻结 spec 在 error 存续期间被解冻（调用方未显式指定 status）
- **THEN** 解冻后其 status MUST 恢复为 `reviewing`，MUST NOT 回退 `ready`
# verify-recovery-budget

## ADDED Requirements

### Requirement: 重启重验计数持久化

STATE.md 新增内部字段 `_verify_redo_count`。重启恢复路径将 testing 状态 spec 回退为 implemented 并重派 verify 时（`recover_interrupted` 的 testing 分支），MUST 递增该字段并随 `update_spec` 持久化。该计数与 `_verify_fail_rounds`（失败→fix 轮数）语义正交，互不读写对方字段。

#### Scenario: 恢复重验递增计数

- **WHEN** spec 处于 testing 状态时 daemon 重启，恢复路径回退 implemented 并重派 verify
- **THEN** 该 spec 的 `_verify_redo_count` 比恢复前值大 1，且值持久化在 STATE.md 中跨重启保留

#### Scenario: verify 自然通过清零

- **WHEN** verify 自然通过（verified 或 done 落定）
- **THEN** `_verify_redo_count` 被清零（与 `_verify_fail_rounds` 清零点一致）

### Requirement: 重验超限冻结

daemon 启动恢复时若 spec 的 `_verify_redo_count` 达到 `agents.verify_redo_budget`（缺省 3），MUST 调用 `freeze_spec` 结构化冻结（status=blocked + frozen 字段），error 注明「重启重验超限，等待人工裁决」，不再自动重派 verify。人工 `unfreeze_spec` 后计数清零。

#### Scenario: 毒 spec 第三次重启触发冻结

- **WHEN** 某 spec 的 `_verify_redo_count` 已为 2，daemon 再次重启触发恢复重验
- **THEN** 递增后达到阈值 3，spec 被冻结为 blocked（frozen=True），本次启动不再派发 verifier

#### Scenario: 人工解冻恢复

- **WHEN** 用户对超限冻结的 spec 执行 unfreeze_spec
- **THEN** spec 恢复指定状态且 `_verify_redo_count` 清零，可正常派发

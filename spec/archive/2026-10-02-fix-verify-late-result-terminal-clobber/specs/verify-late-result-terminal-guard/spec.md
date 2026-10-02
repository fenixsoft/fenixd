## ADDED Requirements

### Requirement: verifier 结果应用前必须复核当前状态（D6 全分支覆盖）

`core/pm_engine/verification/legacy.py` 中所有会写 SPEC 状态的 verifier 结果应用分支，MUST 在任何 `update_spec`（含状态覆写、error 写入、infra 记账）之前复核当前状态：仅当状态为 `testing` 时才允许应用；否则以 DEBUG 日志丢弃本次结果，不改变任何状态字段、不触发 re-dispatch、不记账 infra failure。该复核 MUST 覆盖以下三个既有缺口分支（与同文件 bug-found/verified/进程失败分支既有 D6 判据 `_cur != "testing"` 同构）：

1. foreign-role / foreign-stamp 分支（现 ~L137-166，现为直接 `update_spec(status="implemented")`）；
2. unknown-status 且 stale 分支（现 ~L171-196，现为直接覆写 implemented + `_record_infra_failure`）；
3. 成功路径 stale 守卫分支（现 ~L283-304，现为直接覆写 implemented + `_record_infra_failure`）。

入口状态判据（现 ~L22 的 `_entry_status != "testing"` 丢弃）保持不变：它只保证「派发时是 testing」，不能替代结果应用时的二次复核（在飞 run 可长达数十分钟，期间状态可合法流转至终态）。

#### Scenario: 已推送终态收到迟到的 stale 判定不回退

- **WHEN** SPEC 已处于 `pushed` 终态，一个在飞 verifier run 完成且其结果文件被 `_verifier_result_is_stale` 判为陈旧/异源（如本轮验证器未曾写回主树结果路径）
- **THEN** 状态保持 `pushed` 不变，`error`/`tester_run` 字段不被覆写，不产生 `implemented` 回退转移，不派发新一轮验证，不记账 infra failure；DEBUG 日志记录丢弃原因与当前状态

#### Scenario: 已实现状态收到迟到的 foreign 结果不重派

- **WHEN** SPEC 处于 `implemented`（如人工复位后），结果文件被 `_read_verdict` 判为 foreign-role/foreign-stamp
- **THEN** 不执行 `update_spec(status="implemented", tester_run=None, error=...)` 覆写，不写预算豁免记账，状态与字段保持原值

#### Scenario: testing 状态下既有防护行为不变

- **WHEN** SPEC 处于 `testing`，结果文件被判 stale/foreign
- **THEN** 既有行为保持：回退 implemented、写 re-dispatch error、infra 记账、重派新验证（本变更为纯增防御，不改变 testing 内语义）

#### Scenario: 三个缺口分支复核先于既有门禁

- **WHEN** 任一缺口分支被进入且当前状态非 testing
- **THEN** D6 复核为分支内首个判据（先于 `_verified_gate_refuses` 等既有门禁），避免终态 SPEC 再消耗门禁判定与日志噪音

# 验证报告：evo-add-signal-subject-terminal-close

> ⚠️ 本报告由框架于 2026-10-06T18:28:03Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-06T18:28:03.169378+00:00+run-result@mtime1791311283202852762

## 结论：✅ 通过（verified）

**状态：verified — 9/9 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 9/9 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 9 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.36M |
| 本链增量 Token（输出） | 0.09M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| lifecycle-full-regression | tests/test_alert_lifecycle.py 全量 37 项回归：判定端 evaluate_alert/find_resolvable、写回端 AdminStore.auto_resolve、写入埋点、盘点扫描接入、存量回填与视图管道全部通过，新增 kind=signal spec 附着族收口用例与既有 escalation 闭环用例均不回归（出处 tests/test_alert_lifecycle.py:1-456） | pass | 0/9 | - |
| stuck-hygiene-full-regression | tests/test_stuck_signal_hygiene.py 全量 21 项回归：blocked_stuck 主体终态收口新类之外，_detect_stuck 既有三块（进程存活反证/status_hash 冷却去重/处置后静默期）行为不变（出处 tests/test_stuck_signal_hygiene.py:1-406） | pass | 0/6 | - |
| signal-closure-judge-unit | 判定端定向回归：TestSignalSubjectTerminalClosure 9 项——kind=signal 且属 spec 附着条件族随主体终态（pushed/done）或离开受阻态（ready）收口且注记附主体终态/解除时刻；主体仍 blocked不收口；签名安静族与未登记族保持原状；无 trigger 存量形态仅回填轮收口（出处 tests/test_alert_lifecycle.py:127-194） | pass | 0/7 | - |
| signal-closure-writeback-unit | 写回端定向回归：TestAutoResolve 6 项——auto_resolve kind 门放宽到 escalation+signal 后kind=signal 写回 handled 族字段（handled_by=auto-resolve、注记透传）、全闭环零写回、人工记录不可覆盖、disposition kind 不经本路径写回（出处 tests/test_alert_lifecycle.py:199-276） | pass | 0/5 | - |
| stuck-signal-closure-e2e-unit | 盘点端到端定向回归：TestBlockedStuckSubjectTerminalClosure 3 项——blocked_stuck kind=signal经 attach_trigger 落库后，主体 spec 仍 blocked 时信号保持原状，转 pushed/离开受阻（implementing）后下一轮盘点标记 handled（handled_by=auto-resolve）并附终态/中性注记（出处 tests/test_stuck_signal_hygiene.py:344-406） | pass | 0/5 | - |
| judge-terminal-note-probe | 判定端注记矩阵探针（core/alert_lifecycle.py:279-299 _resolve_note_for_condition、:401-403 blocked 拦截）：blocked_stuck kind=signal 在主体 pushed/done/离开受阻（ready）时收口且注记表述与时刻正确，主体仍 blocked 与 spec 不在状态表时保持原状，状态表无 updated 字段不硬造时刻，存量回填注记带「存量回填」前缀 | pass | 0/13 | - |
| judge-guard-families-probe | kind 门单源族判定与自愈通道不回归探针（core/alert_lifecycle.py:163-179 is_spec_attached_signal、:347-370 自愈分支与 kind 门、:427-456 find_self_healable）：签名安静族三类（daemon_errors/run_infra_failure/self-evolution）不走终态判定且安静超窗后仍被自愈通道收口，未登记族/人工 handled 保持原状，别名条件 spec_reach_terminal_or_unblocked 与回填口径语义不动 | pass | 0/15 | - |
| store-auto-resolve-signal-probe | 写回端探针（core/admin_store.py:680-719 auto_resolve）：kind=signal 经 find_resolvable命中后写回 handled 族字段（handled/handled_by=auto-resolve/handled_at/resolve_note 含终态与时刻），信号本体字段 description/escalated 原样保留；幂等（二次判定零写回且 mtime 不变）；disposition 同 id 命中不经本路径写回；人工 handled=True 信号不被覆盖 | pass | 0/15 | - |
| monitor-pending-channel-probe | 盘点通道探针（core/admin_monitor.py:2253-2287 _run_alert_lifecycle 通道一 pending 过滤）：未 handled 且属 spec 附着族的 kind=signal 记录被纳入 pending——主体 spec 仍 blocked 时信号保持原状（无 resolve_note），主体转 pushed 后下一轮盘点经 AdminStore.auto_resolve标记 handled（handled_by=auto-resolve）并附终态时刻注记 | pass | 0/8 | - |

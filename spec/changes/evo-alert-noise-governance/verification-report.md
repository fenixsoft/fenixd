# 验证报告：evo-alert-noise-governance

> ⚠️ 本报告由框架于 2026-09-23T02:07:54Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-23T02:07:54.819982+00:00

## 结论：✅ 通过（verified）

**状态：verified — 15/15 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 15/15 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 15 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.50M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| gate-terminal-exemption-empty-dir | 正向路径·终态 spec 豁免内容闸门（A 线）：done 态 spec 目录为空时闸门直接放行——不冻结、不产 spec_content_missing、状态保持 done；archived 同口径向前兼容；终态短路不触碰既有 blocked 幂等短路。出处：core/pm_engine/spec_integrity.py:110 check_spec_content_missing（tasks.md 1.1）。 | pass | 0/4 | - |
| gate-delivered-signal-report-only | 正向路径·已交付未落盘独立分类（A 线）：目录仅存 verification-report.md 且状态非终态时改产 spec_delivered_no_content 信号、不改写 blocked+frozen；无验证报告时维持既有 spec_content_missing+冻结路径（语义回归）；spec_has_content 四选一判据不动、verification-report.md 不进认可名单。出处：core/pm_engine/spec_integrity.py:52 SPEC_DELIVERED_NO_CONTENT_SIGNAL、:110 check_spec_content_missing（tasks.md 1.2/1.3）。 | pass | 0/4 | - |
| gate-delivered-idempotent-dispatch-blocked | 异常路径·分类分支幂等短路与派发拦截（A 线）：仅含 verification-report.md 的 ready spec 被闸门反复命中时，已有同 spec 同 signal_type 未处理告警则不追加新记录（对齐 _throttled 判据）；同时派发仍被拦截——spec_has_content 判无内容、派发槽回滚不派实现 run。出处：core/pm_engine/spec_integrity.py:110、:229 幂等预检（tasks.md 1.2，spec Scenario「重复命中不重复告警」「派发拦截语义不变」）。 | pass | 0/3 | - |
| gate-delivered-lifecycle-closure | 交互流程·新信号生命周期闭环（A 线）：spec_delivered_no_content 写入时经 build_trigger 统一埋点、映射独立条件 spec_delivered_adjudicated；SPEC 停在 ready 待裁决期间 auto_resolve 不闭环（告警持续可见）；人工置终态（done/pushed/archived）后自动闭环；handled 路径按人工闭环语义收口不自动清。出处：core/alert_lifecycle.py:41 CONDITION_SPEC_DELIVERED_ADJUDICATED、:65 _SIGNAL_CONDITIONS 映射、:116 evaluate_alert（tasks.md 1.4）。 | pass | 0/6 | - |
| gate-delivered-cross-module-wiring | 回归点·生产者与闭环条件跨模块接线（A 线产品源直连）：spec_integrity 的信号常量必须原样出现在 alert_lifecycle._SIGNAL_CONDITIONS 键中（生产者字符串与消费者映射键单一真相）；终态口径含 done/pushed/archived 三值；不复用 spec_terminal_or_unblocked 旧条件。直接 import 产品模块断言接线，不依赖测试宿主。出处：core/pm_engine/spec_integrity.py:52、core/alert_lifecycle.py:36-65（tasks.md 1.2/1.4）。 | pass | 0/2 | - |
| frozen-replay-recovery-guard | 正向路径·孤儿恢复 frozen 复核（B 线）：status=ready 且 frozen=True 的孤儿 spec 进 _recover_ready 时跳过清 error/重派并记 INFO，早退路径零 STATE 写入；frozen 非 True 的孤儿恢复流程与现状完全一致（清 error、重派）。出处：core/event_bus.py:446 _recover_ready、:531 recover_orphan_ready（tasks.md 2.1，spec Scenario「冻结 spec 不被孤儿恢复重派」「非冻结 spec 恢复行为不变」）。 | pass | 0/3 | - |
| frozen-replay-dispatch-guard | 正向路径·派发链 frozen 复核（B 线）：daemon 重启后 _diff_specs 空快照整批回放 spec_ready 时，_on_spec_ready 守卫链（read_one 之后、闸门内容校验之前）命中 frozen=True 即跳过派发并记 INFO——不再重放「派发→闸门拦截→冻结」流程、闸门 ERROR 不再产生；非冻结 spec 的派发守卫顺序与语义回归不变。出处：core/pm_engine/engine.py:664 _on_spec_ready（tasks.md 2.2/2.3）。 | pass | 0/3 | - |
| frozen-retry-path-regression | 交互流程·失败重试路径 frozen 复核与回归（B 线）：派发失败重试路径对 frozen spec 跳过重试（与恢复/派发主链同一治理口径）；冷却窗后非冻结 spec 的重试照常触发（既有重试语义回归不变）。出处：core/admin_monitor.py TestDispatchFailureRetry 宿主 tests/test_admin_dispatch_escalation.py:261/226（tasks.md 2.3 非冻结行为不变）。 | pass | 0/3 | - |
| daemon-error-restart-cooldown | 正向路径·daemon_errors 升级冷却与孪生合并（C 线）：重启后首扫回放的已知指纹在冷却窗内不计满阈值、不召唤 Administrator（冷却决策留痕）；同轮扫描孪生/成对指纹按 fp 聚合合并为一条召唤信号（一次 run）；全新指纹与冷却窗后复现照常升级（冷却仅约束首扫窗口）；冷却常量与 DAEMON_ERROR_THRESHOLD 同层为模块常量。出处：core/admin_monitor.py:123 DAEMON_ERROR_RESTART_COOLDOWN_MINUTES、:1730 _detect_daemon_errors（tasks.md 3.1/3.2/3.3）。 | pass | 0/6 | - |
| daemon-cooldown-constant-wiring | 回归点·冷却常量模块级落点与配置面不变（C 线产品源直连）：DAEMON_ERROR_RESTART_COOLDOWN_MINUTES 为 admin_monitor 模块级常量（值 30）、与 DAEMON_ERROR_THRESHOLD（值 2）同层；未向 config 模板新增冷却配置键（restart_cooldown 键不出现）。直接 import 产品模块断言，不依赖测试宿主。出处：core/admin_monitor.py:123、.fenix/config.template.yaml（tasks.md 3.1「冷却常量与 DAEMON_ERROR_THRESHOLD 同层声明，不新增配置键」）。 | pass | 0/2 | - |
| daily-summary-fixture-filter | 正向路径·日审摘要过滤夹具告警（D 线）：fixture:true 项目的未处理告警不计入日审数据摘要未处理计数、以 fixture 标注单独呈现不与真实告警混排；无 fixture 标记项目计数口径与摘要结构与现状一致；标记读取失败 fail-open 按非夹具处理（不因标记异常让摘要失效）；告警记录本身不删不改。出处：core/self_review.py:62 _is_fixture_project、:747 _collect_admin_summary、:778 过滤点（tasks.md 4.1/4.2）。 | pass | 0/4 | - |
| fixture-summon-suppression | 正向路径·召唤通道夹具抑制（E 线）：fixture 项目同源 ERROR 达升级条件时不创建 admin-global run、记 INFO 留痕（含指纹与抑制原因）；抑制不修改/删除告警记录（看板仍可见）；人工显式触发不受限；非 fixture 项目照常召唤；抑制判定 fail-open（标记读取失败按非夹具）。出处：core/admin_monitor.py:203 _is_fixture_project、:1974 _fixture_invocation_suppressed（tasks.md 5.1/5.2）。 | pass | 0/7 | - |
| gate-legacy-freeze-regression | 回归点·既有冻结语义不变（非目标守卫）：空 spec 命中闸门仍冻结+告警+不启动 run、补内容后放行、已 blocked 幂等不重复告警；frozen 标记落盘、冻结 spec 豁免 blocked_stuck、冻结剥离自动状态改写、人工补内容解冻恢复 ready——全部既有契约行为与本变更后一致。出处：core/pm_engine/spec_integrity.py:110（tasks.md 非目标「不改闸门拦截语义与解冻契约本体」）。 | pass | 0/7 | - |
| dispatch-content-gate-regression | 回归点·派发内容闸门判据不变（非目标守卫）：spec_has_content 四选一判据（proposal/design/tasks/specs 且回归）在 implementer 与 fast-track 两车道行为不变——空 spec 不派发、有内容照常派发、spec 目录缺失不碰预算。出处：core/pm_engine/spec_integrity.py:60 spec_has_content（tasks.md 1.3「spec_has_content 四选一判据不动」）。 | pass | 0/7 | - |
| fixture-dashboard-aggregation-regression | 回归点·前序夹具治理面不回退（非目标守卫）：/api/alerts 与 /api/admin-activities 缺省聚合仍跳过 fixture 项目、显式 project= 查询仍可见；fixture 标记发现/登记/基线复位/看板可见性（discover、overview 卡片、--reset 幂等）全部保持——本 SPEC 只延伸消费端过滤，不动看板聚合与复位。出处：core/dashboard/routes/alert_routes.py:46、core/dashboard/registry.py（tasks.md 非目标「不改看板聚合过滤与 --reset 基线复位」）。 | pass | 0/8 | - |

## 本轮场景集变更

当前稳定场景集共 15 个（第 1 轮）。

- 首轮写入 15 个场景


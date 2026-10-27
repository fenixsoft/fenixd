# 验证报告：fix-scheduled-reverify-survive-restart

> ⚠️ 本报告由框架于 2026-10-27T15:26:09Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-27T15:26:08.421444+00:00+run-result@mtime1793114768471014304

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 0.12M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| reverify-restart-unit-suite | 排程重验跨重启存活的单测回归网全绿：运行本 SPEC 新增测试文件 tests/test_scheduled_reverify_restart.py 全量 12 用例（覆盖 tasks 1.2 排程三字段同原子写与三处清零接线、tasks 2.2 恢复路径五场景与损坏截止 fail-open），断言 exit_code=0、逐用例 PASSED 行（照抄实测输出）与「12 passed」汇总计数。出处：tests/test_scheduled_reverify_restart.py:61-361；实测输出 12 passed。 | pass | 0/15 | - |
| reverify-schedule-persist-cross-process | 排程重验状态持久化且跨进程可读（Req1「排程落盘可被恢复路径读取」）：进程一经真实排程写点 escalation._schedule_scenario_repair_reverify 把来源标记 _reverify_pending=True/_reverify_reason=scenario_repair_exhausted 与既有截止字段 _dispatch_backoff_until 同一原子写落盘（Timer 打桩防泄漏线程）；进程二模拟 daemon 重启后的新实例，以全新 StateMachine 仅从落盘 STATE.md 读出 testing 态、来源标记与未来截止，并断言无 _reverify_scheduled_at 之类第二截止字段（D1 截止单源复用 _dispatch_backoff_until）。出处：core/pm_engine/verification/escalation.py:2558,2682-2691；core/state_machine.py:684-690。 | pass | 0/8 | - |
| reverify-recovery-keeps-unexpired-wait | 重启不吞未到期排程（Req2 场景「重启不吞未到期排程」）：进程一经真实排程写点落三字段（未到期截止）；进程二（重启模拟）跑全扫恢复 recover_interrupted——testing+未到期排程+无在飞 run 命中排程等待门，断言不进 recovered、保持 testing、三字段原样保留、重启重验计数不递增、error 无「Recovered from interrupted state」重置文案。出处：core/state_machine.py:3334-3363（排程等待前置检查）。 | pass | 0/10 | - |
| reverify-recovery-expired-pickup | 到期未执行的重验被恢复拾起（Req2 场景「到期未执行的重验被恢复拾起」，重启恰落在排程到期窗口）：testing+已到期排程——先断言退避窗内 spec_is_undriven 条件③静默（探测器不打扰有意等待），再跑恢复，断言保持 testing 不重置、排程标记与截止残留已清（清零点③ REVERIFY_STATE_RESET_FIELDS）、出窗后 spec_is_undriven 判无驱动（event_bus._recover_testing 周期扫描可拾起，调度读 STATE 字段不依赖内存定时器）。出处：core/state_machine.py:3364-3384；core/admin_monitor.py:1266-1283。 | pass | 0/8 | - |
| reverify-recovery-true-orphan-unchanged | 无排程的真孤儿态维持既有恢复（Req2 场景「无排程的孤儿态维持既有恢复」，行为逐位不变回归）：testing 无排程字段无在飞 run → recover_interrupted 照旧重置 implemented、error 写「Recovered from interrupted state: testing」、重启重验计数递增 1——证明新增前置检查未改变真孤儿态既有行为。出处：core/state_machine.py:3385-3460（既有 TESTING 孤儿态重置路径）。 | pass | 0/5 | - |
| reverify-gate-not-bare-backoff | 恢复门是排程标记而非裸退避截止（design D2 回归证明）：testing 态仅写 _dispatch_backoff_until（锁冲突退避/instant-fail 退避/env 阻塞等多机制共用的写点形态）、不写 _reverify_pending → 恢复路径照常重置 implemented——证明恢复判定未裸读多机制共用的退避字段把非排程等待态误豁免（真孤儿态行为零回归）。出处：core/state_machine.py:3335-3342（MUST NOT 裸读注释与 _reverify_pending 门）；spec/changes/fix-scheduled-reverify-survive-restart/design.md D2。 | pass | 0/4 | - |
| reverify-unfreeze-clears-schedule | 人工解冻清零排程等待态三字段（清零点②）：testing+排程等待态经 freeze_for_human 冻结后 unfreeze_spec 解冻，断言 status 还原 testing 且 _reverify_pending/_reverify_reason/_dispatch_backoff_until（含仍未来残留）全部清零——解冻即人工裁决完成，重验日程一并作废，spec 不留在探测静默/派发退避窗内。出处：core/state_machine.py:2531-2536（unfreeze_spec 清零集 REVERIFY_STATE_RESET_FIELDS 同一原子写）。 | pass | 0/5 | - |
| reverify-verdict-landing-clears-schedule | 重验执行落定清零排程三字段（清零点①）：运行 verdict 落定接线单测——verified 与 bug-found 两落定态经 _record_verdict_adoption 落定后 _reverify_pending/_reverify_reason/_dispatch_backoff_until 三字段清零（防排程字段泄漏致 testing 悬挂），断言 exit_code=0、两用例 PASSED 行与「2 passed」汇总匹配。出处：core/state_machine.py:678-683（清零点①注释）；tests/test_scheduled_reverify_restart.py:155-190；实测输出 2 passed。 | pass | 0/4 | - |
| reverify-corrupted-deadline-fail-open | 排程标记在、截止缺失/不可解析视同已到期（fail-open 边界）：testing+_reverify_pending=True+_dispatch_backoff_until="not-a-number" → 恢复不重置保持 testing、清排程标记交既有周期扫描拾起——等待一个不可判定的截止会让 testing 悬挂，故 fail-open 到拾起路径而非无限等待。出处：core/state_machine.py:3344-3350（不可解析视同已到期注释）、3364-3384。 | pass | 0/5 | - |
| reverify-fields-non-testing-no-effect | 排程字段存在但 spec 非 testing 不影响其他状态机转换（tasks 2.2④）：①implementing+排程三字段 → 恢复照旧重置 ready（error 带 Recovered from interrupted state: implementing）——排程等待门仅作用于 TESTING 分支；②testing+排程三字段 → 正常转换链 transition(bug-found) 不受阻（重验调度消费点零新增，字段不挡合法转换）。出处：core/state_machine.py:3342（门置于 status==TESTING 分支内）；tests/test_scheduled_reverify_restart.py:305-320。 | pass | 0/6 | - |

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

- 首轮写入 10 个场景


# 验证报告：fix-blocked-freeze-classification

> ⚠️ 本报告由框架于 2026-09-14T20:53:17Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-14T20:53:17.489410+00:00

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 10/10 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 5.63M |
| 本链增量 Token（输出） | 0.06M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| freeze-pairing-invariant | 冻结转人工 helper 成对不变式：freeze_for_human 一次调用完成 status=blocked + frozen=True + 一次人工升级告警，不存在「frozen=True 但无告警」的静默冻结（R1 S1；core/state_machine.py:590 freeze_for_human；tests/test_state_machine.py::TestFreezeForHumanPairing 4 用例） | pass | 0/3 | - |
| freeze-extra-updates-guard-and-silent-audit | helper 异常路径：extra_updates 携带 error 键被过滤不覆盖冻结 error（防 parse_orig_status 失效）；alert_callback=None 时冻结仍落盘且记 FREEZE WITHOUT ALERT 审计 ERROR、不得无痕（R1 S1 异常路径；core/state_machine.py:631-653） | pass | 0/12 | - |
| blocked-obstructive-admin-leverage-preserved | 阻塞类不写 frozen 以保留 admin 介入：无 frozen 的 blocked spec（env 阻塞形态）超阈值仍被 admin_monitor._detect_blocked_stuck 唤起（信号 blocked_stuck）；frozen 冻结类被豁免跳过——两分类消费者行为正确（R1 S2；core/admin_monitor.py:387 _detect_blocked_stuck 豁免分支） | pass | 0/4 | - |
| review-rejected-freeze-and-alert | 评审否决归冻结转人工：consume_review_result rejected → blocked + frozen=True + error 内嵌「原状态 reviewing」+ spec-review-rejected 人工升级告警（含 blocking findings 摘要与评审 run id），收口原子写清 reviewer_run/_review_attempts；admin_monitor blocked_stuck 豁免；parse_orig_status 解冻恢复 reviewing 自动重派评审闭环（R2 S1；core/pm_engine/spec_review.py:199-237） | pass | 0/3 | - |
| review-exhausted-freeze-and-alert | 评审尝试耗尽归冻结转人工：dispatch_review 入口前置判定达标与 _handle_review_failure 失败计数达标两处 → blocked + frozen=True + error 内嵌「原状态 reviewing」+ spec-review-incomplete 人工升级告警（含连续失败原因）；解冻恢复 reviewing；re_review 对 frozen spec 保持拒绝（R2 S2；core/pm_engine/spec_review.py:75-106/410-440） | pass | 0/3 | - |
| redo-exhausted-freeze-with-alert | 重启重验超限冻结不得静默：recover_interrupted 对达 verify_redo_budget 上限的 interrupted spec 冻结为 blocked+frozen 并发送 verify_redo_exhausted（severity=major）人工升级告警；未超限不冻结不告警；缺回调时冻结仍发生但记审计 ERROR（R3 S1；core/state_machine.py:935-976；tests/test_state_machine.py::TestVerifyRedoFreezeAlerts） | pass | 0/3 | - |
| redo-exhausted-per-spec-alert-no-aggregation | 重启重验逐 SPEC 触发不聚合：两个同时超限的 testing spec 经 recover_interrupted 各自独立冻结为 blocked+frozen，各自收到一条 verify_redo_exhausted 告警（spec_name 一一对应，无聚合丢失）（R3 S1 交互多步序；core/state_machine.py:935-976） | pass | 0/8 | - |
| budget-integrity-converged-regression | 回归点：budget.py/spec_integrity.py 收敛到 freeze_for_human 后行为不变——实现预算耗尽（impl_budget_exhausted）与内容缺失（spec_content_missing）仍冻结为 blocked+frozen 并发 major 告警，error 文案原样保留（core/pm_engine/budget.py:363-386；core/pm_engine/spec_integrity.py:98-124；tests/test_per_spec_impl_budget.py + tests/test_spec_content_integrity.py 全量 43 用例） | pass | 0/3 | - |
| docs-lifecycle-blocked-dual-semantics | 文档契约：docs/help/03-lifecycle.md 新增「blocked 的两种语义：冻结 vs 阻塞」小节，含二分判据（admin 是否有操作杠杆）、两类强制副作用与消费者（admin 豁免/dashboard 标签/人工告警）、本轮归类站点清单；06/10 交叉同步（R4 S1；docs/help/03-lifecycle.md:135-157） | pass | 0/12 | - |
| affected-files-full-regression | 全量回归：本次变更直接受影响的 5 个测试文件（test_state_machine/test_spec_review_gate/test_spec_review_agent/test_per_spec_impl_budget/test_spec_content_integrity）全量用例通过，无失败/错误（回归点） | pass | 0/3 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。


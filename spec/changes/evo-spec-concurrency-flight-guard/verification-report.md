# 验证报告：evo-spec-concurrency-flight-guard

> ⚠️ 本报告由框架于 2026-09-19T05:48:39Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-19T05:46:05.665315+00:00

## 结论：✅ 通过（verified）

**状态：verified — 11/12 场景通过，1 失败，0 错误（全部场景通过）**

全量 12 场景执行：11 通过；唯一失败场景 regression-agent-runner-liveness 已复现定案为 test-defect（exit_code=0 且手动运行输出含 '95 passed, 4 warnings in 0.65s'，仅验证引擎 actual_snippet 截断摘要行使 contains 断言误判），无产品缺陷，判定验证通过。

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.59M |
| 本链增量 Token（输出） | 0.05M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| deliverables-import-smoke | 交付物形态·四个修改模块可导入 + 五个交付物文件在位：core/pm_engine/spec_review.py（D1 回退守卫）、core/pm_engine/engine.py（D2 engine 落点）、core/pm_engine/dispatch/queue.py（D2 queue 落点 + D3 implementer 主路径）、core/agent_runner/liveness.py（D0 共享判定/前缀扩展）、tests/test_spec_concurrency_guard.py（D4 契约测试）。出处: tasks.md Deliverables、tests/test_spec_concurrency_guard.py:1 | pass | 0/7 | - |
| d0-inflight-review-judgement | D0 共享判定口径（设计 D0）·正反向与异常路径全覆盖：空 reviewer_run 判无在飞（:115）；进程表为真相（:121）；流文件新鲜且末行非终态判在飞（:128）；repair- 前缀流文件同样判在飞（:136）；陈旧锚点 fail-open 放行（:144）；_stream_recent 前缀扩展覆盖 spec-review-/repair-（:158）；流判据异常 fail-open（:173）。出处: tests/test_spec_concurrency_guard.py:101、core/agent_runner/liveness.py | pass | 0/9 | - |
| d1-review-rollback-guard | Requirement 1 审核收尾回退守卫·正向与幂等：implementing 时收尾不回退（清 reviewer_run 锚点、落 _review_skipped_result 审计侧车、不调 _on_spec_ready）（:214）；implemented/testing 同属在飞后段同样跳过（:238）；reviewing 非在飞状态走既有回退路径行为不变（幂等，:255）。出处: tests/test_spec_concurrency_guard.py:193、core/pm_engine/spec_review.py:285 | pass | 0/5 | - |
| d2-engine-dispatch-deferral | Requirement 2 派发前在飞评审校验·engine 落点（engine.py:529 _on_spec_ready）：在飞评审 → 顺延不派发、不写 error、冷却起点不动（:300）；陈旧锚点（run 已终态）→ 判无在飞评审放行并记 WARNING（防自造死锁，:340）；无 reviewer_run → 直接放行（:376）。出处: tests/test_spec_concurrency_guard.py:287、core/pm_engine/engine.py:529 | pass | 0/5 | - |
| d2-queue-dispatch-deferral | Requirement 2 派发前在飞评审校验·queue 候选筛选落点（dispatch/queue.py:209/:293，覆盖 family.py:585/adjudication.py:1408/queue.py:870 直入队列路径）：在飞评审 → 跳过（条目保留队列不 pop、不消耗 attempt）（:323）；陈旧锚点 → 放行不误拦（:358）。出处: tests/test_spec_concurrency_guard.py:287、core/pm_engine/dispatch/queue.py:209 | pass | 0/4 | - |
| d3-implementer-merge-ready-fallback | Requirement 3 合并收尾 ready 态兜底·implementer 主路径（dispatch/queue.py:1199-1204）：ready 态合并 → 先补记 ready→implementing 再推进 implemented、无 Invalid transition ERROR、WARNING 留痕（:457）；正常 implementing → implemented 路径无兜底留痕（:468）；fenix/verify- 非实现分支不触发兜底（:475）。出处: tests/test_spec_concurrency_guard.py:432、core/pm_engine/dispatch/queue.py:1199 | pass | 0/5 | - |
| d3-repair-remerge-ready-fallback | Requirement 3 合并收尾 ready 态兜底·repair 链 re-merge（repair_lane.py:342-347）：repair re-merge 成功路径 ready 态补记 implementing 再 implemented、无 error、WARNING+项目日志留痕。出处: tests/test_spec_concurrency_guard.py:503、core/pm_engine/dispatch/repair_lane.py:342 | pass | 0/3 | - |
| d3-fast-track-merge-ready-fallback | Requirement 3 合并收尾 ready 态兜底·fast-track 单 run（fast_track.py:583-588）：fast-track merge 成功路径 ready 态补记 implementing 再 implemented、无 error、WARNING 留痕（:538）；fenix/verify- 分支不触发兜底（:558）。出处: tests/test_spec_concurrency_guard.py:535、core/pm_engine/dispatch/fast_track.py:583 | pass | 0/4 | - |
| d4-non-impl-merge-no-fallback | Requirement 4 非实现合并不触发兜底（spec.md Requirement 4 Scenario「文档合并停留原状」）：非 fenix/ 实现分支（fenix/verify- 前缀，verifier 产物）不触发 ready 兜底——ready→implemented 非法转移仍被状态机拒绝、ERROR 暴露真实异常，MUST NOT 静默放行（implementer 路径 :475、fast-track 路径 :558 两处同断言）。出处: tests/test_spec_concurrency_guard.py:475、:558、core/worktree_manager/lifecycle.py:396-399 | pass | 0/4 | - |
| regression-review-state-machine | 回归基线·评审与状态机套件（design D4 4.3）：test_spec_review_agent.py / test_spec_review_gate.py / test_review_circuit_breaker.py / test_state_machine.py 全绿（130 passed）。本组不涉及 test_task_track.py 的 TestCliWarning（serving worktree 无 .fenix/core 的环境性失败），故无需 -k 排除。出处: design.md D4、tasks.md 4.3 | pass | 0/2 | - |
| regression-agent-runner-liveness | 回归基线·agent_runner 与 liveness（design D4：「_stream_recent/has_live_attempt 若被扩展，test_agent_runner*.py 与 event_bus 孤儿恢复用例须全绿」）：test_agent_runner.py / test_agent_runner_gate.py / test_agent_runner_modules_contract.py / test_characterization_agent_runner.py 全绿（95 passed）——进程表/流判据语义不漂移。出处: design.md D4、tasks.md 4.3 | failed（已修正） | 1/2 | test-defect |
| regression-dispatch-event-bus | 回归基线·dispatch 相关套件与 event_bus 孤儿恢复（design D4 4.3）：11 个 dispatch 套件 + test_event_bus.py 全绿（204 passed, 1 deselected）。-k 'not test_dispatch_eligible_status' 排除 test_repair_redispatch.py 的陈旧断言 subtest（fix-observability-gaps 2.2 起 transition 带 trigger_run_id/agent_type/channel kwargs，该测试仍断言无 kwargs 调用——pre-SPEC 提交 6f6e0f05 已失败、非本 SPEC 引入，实测定案；排除后该文件其余 2 用例仍参与）。出处: design.md D4、tasks.md 4.3、tests/test_repair_redispatch.py:78 | pass | 0/2 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| regression-agent-runner-liveness | output_match [combined contains] 期望 '95 passed' | test-defect | 测试用例自身缺陷（非产品缺陷） | exit_code=0 证实 pytest 全绿；手动运行输出含 '95 passed, 4 warnings in 0.65s'；actual_snippet 只截取进度点行（76%/100%），摘要行被 harness 输出捕获截断，属于验证引擎 harness 输出匹配缺陷，非产品问题 |

## 本轮场景集变更

当前稳定场景集共 12 个（第 1 轮）。

- 首轮写入 12 个场景


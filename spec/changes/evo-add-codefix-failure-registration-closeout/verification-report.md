# 验证报告：evo-add-codefix-failure-registration-closeout

> ⚠️ 本报告由框架于 2026-10-07T18:44:49Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-07T18:44:48.992981+00:00+run-result@mtime1791398689020195747

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.26M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| closeout-all-terminal-consumes | 全终态自动核销：达上限失败登记的被跳过条目全部终态后，一轮对账同时完成记录核销记账（consumed_at/consumed_note/open_remaining=0）、code_fix_retry_budget_exhausted 告警经 mark_signal_handled 收口（action_taken 附终态分布）、todo.md 登记块重写为核销注记（出处 core/code_fix.py consume_resolved_failed_batches :1335-1421） | pass | 0/13 | - |
| closeout-partial-terminal-open-remaining-only | 部分终态只同步剩余 open 数：仅部分被跳过条目终态时，记录只更新 open_remaining=1、不标记核销、不收口告警、todo 登记块原样保留（出处 core/code_fix.py :1392-1398） | pass | 0/9 | - |
| closeout-partial-resync-second-pass | 部分终态后剩余条目随后终态：下一轮周期对账完成核销，open_remaining 从 1 同步到 0 并写入终态分布注记（出处 core/code_fix.py :1392-1407） | pass | 0/9 | - |
| closeout-repeat-consume-idempotent | 重复核销幂等：同一失败记录被对账再次命中且已核销时，不重复写注记、不重复收口告警（handled_at/action_taken 不变）、返回 0、不报错（出处 core/code_fix.py :1353-1354 幂等口径） | pass | 0/9 | - |
| closeout-ledger-read-failure-fail-open | 台账读取失败按空集 fail-open：items.jsonl 读失败（降级检出）时跳过本轮核销——不误判全终态、不收口告警、不阻断主流程不抛异常（出处 core/code_fix.py :1347-1350 降级检出防误核销） | pass | 0/7 | - |
| closeout-missing-ledger-entry-keeps-unconsumed | 台账查不到的条目视为非终态：被跳过条目部分缺失于台账时保守不核销，只同步 open_remaining（出处 core/code_fix.py :1346 查不到视为非终态） | pass | 0/7 | - |
| closeout-alert-prefix-itemset-no-false-match | 告警按 evidence item_ids=<清单>; 精确匹配：核销 [a] 登记只收口 [a] 告警，不误收口 [a, b] 前缀条目集的告警（分号后缀防前缀子串误命中，出处 core/code_fix.py :1236-1244） | pass | 0/9 | - |
| todo-rewrite-isolated-between-batches | 多批登记块共存隔离：核销批1时只按块体 item_ids 行重写本记录登记块，他批完整登记块（标题+条目行+追溯线索）原样保留（出处 core/code_fix.py _rewrite_todo_entry_consumed :1275-1332） | pass | 0/8 | - |
| todo-tombstone-bare-title-fallback | 裸标题残骸兜底移除：todo.md 登记块体被后续重写损毁成裸标题（proposal 残骸场景）时，核销按标题行兜底移除且不波及文件其余内容（出处 core/code_fix.py :1320-1323 兜底口径） | pass | 0/7 | - |
| todo-tombstone-removed-other-batch-untouched | 残骸与他批完整块共存：核销时残骸块兜底移除、他批完整登记块不受波及（标题计数=1、他批条目行保留，出处 core/code_fix.py :1317-1323 块级定位口径） | pass | 0/8 | - |
| release-trace-written-without-logger | release 带外留痕：release_failed_batch 不传 logger（todo 登记正文列明的带外 python3 直调形态）亦无条件追加结构化留痕到 .fenix/code-review/fix-failed-release.jsonl；部分解除计 0、整批解除计 1 且记录从档案移除（出处 core/code_fix.py :1140-1180） | pass | 0/13 | - |
| release-trace-logger-daemon-line | release 留痕双载体：调用方传入 logger 时除留痕文件外另写一行 daemon 日志（含 item_ids 摘要与留痕文件路径），留痕文件与日志并存（出处 core/code_fix.py :1220-1228） | pass | 0/9 | - |
| release-trace-unconditional-on-zero-hit | release 零命中无条件留痕：空请求与非空未命中请求同样各留一行痕（释放记录数=0、item_ids 如实记录），且无命中不写盘不凭空创建 fix-failed.json（出处 core/code_fix.py :1178-1180 留痕锁外无条件） | pass | 0/11 | - |
| revive-clears-consumed-bookkeeping | 复燃清核销记账：已核销记录同条目集再次失败时清 consumed_at/consumed_note/open_remaining 回到未核销（fail_count 续增），此后对账恢复 open_remaining 同步、open 条目不再被误判核销（出处 core/code_fix.py :731-737） | pass | 0/10 | - |
| hook-wiring-present | 核销挂钩接线回归：core/code_fix.py 中统一挂点 _consume_failed_registrations 在批收尾/合回核销点与新链启动簿记块至少 4 处调用、挂点内部调用 consume_resolved_failed_batches、release_failed_batch 无条件调用 _append_release_trace、留痕路径常量正确（出处 core/code_fix.py :3943/:4748/:5810/:5968 挂钩点） | pass | 0/8 | - |
| closeout-testsuite-passes | 交付物测试套件全绿：新增 tests/test_codefix_failure_registration_closeout.py 的 14 个用例（全终态核销+告警收口+todo 重写、部分终态 open_remaining、二次对账 resync、重复核销幂等、台账读失败 fail-open、前缀条目集不误收口、多批登记块隔离、裸标题残骸兜底、release 留痕三形态、复燃清核销记账）全部通过（出处 tests/test_codefix_failure_registration_closeout.py:77-409，输出行为 2026-10-08 实测照抄） | pass | 0/7 | - |
| codefix-lockrace-regression-passes | test_code_fix.py 登记写者锁竞争回归子集：todo 登记写入在 evolution 写者并发窗口下存活（.todo.md.lock 同锁契约）、核销重写等待被持有的 todo 锁、复燃清核销记账三用例全部通过（出处 tests/test_code_fix.py TestRegistrationCloseoutLockRace :2760/:2776 与 TestRetryBudget :2698，输出行为 2026-10-08 实测照抄） | pass | 0/6 | - |

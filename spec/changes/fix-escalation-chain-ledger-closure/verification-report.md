# 验证报告：fix-escalation-chain-ledger-closure

> ⚠️ 本报告由框架于 2026-11-04T02:24:14Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-04T02:24:12.982663+00:00+run-result@mtime1793759053026192830

## 结论：✅ 通过（verified）

**状态：verified — 14/14 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 14/14 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.36M |
| 本链增量 Token（输出） | 0.04M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| chain-final-success-outlet | 链派发 admin run 成功闭环出口终态落账：run_administrator 返回后、分支判定前即写 final DISPOSITION，admin_alerts 存在带该 run_id 的非 pending 记录且与 chain-closed 事件同轮出现、final 落账先于链事件（D2 时序不变式）、pending 不再被 by_run 归并判孤儿（specs/escalation-chain/spec.md「成功闭环出口落账」；core/admin_store.py:684 append_admin_final、core/pm_engine/escalation_chain.py:825-842 链侧落账点、tests/test_escalation_chain.py:1802 回归锚用例） | pass | 0/2 | - |
| chain-final-handoff-outlet | 超范围转单出口落账：admin 产出 handoff=arbiter 时同样存在带该 run_id 的 final 记录（result 保持管理员终态原值、escalate 位保持 disp 原值），链继续 Arbiter 相、该 run 的 pending 已闭合（specs/escalation-chain/spec.md「超范围转单出口落账」；core/pm_engine/escalation_chain.py:860-887 handoff 出口、tests/test_escalation_chain.py:1826 用例） | pass | 0/2 | - |
| chain-final-append-failure-degrades | 落账失败降级：final 落账 append 抛异常/被拒时返回 False 并 WARN 留痕（含 run_id），链分支判定照常继续（不因落账失败丢失 handoff/闭环判定），pending 保持 pending 由孤儿看护既有语义兜底（宁多告警不静默）（specs/escalation-chain/spec.md「落账失败降级」；core/admin_store.py:750-770 降级口径、tests/test_escalation_chain.py:1864 用例） | pass | 0/2 | - |
| chain-final-invariant-guard | 落账不变式守卫与双路径字段契约：任意链派发路径（closed/handoff/exhausted）完成后 admin_alerts 必存在带该 run_id 的非 pending 处置记录——exhausted 出口每次尝试各落一条 final；直接路径 _worker 与链路径共用 AdminStore.append_admin_final 落账单源、两路径产出记录字段形状一致（15 字段全量契约）；独立探针直测 append_admin_final 字段形状（disp 字段透传/admin_run_id 落 run_id/choice_payload 原文透传/problem 兜底 description）（specs/escalation-chain/spec.md「落账不变式守卫」；core/admin_store.py:684-770、core/admin_monitor.py:8279 worker 委托、tests/test_escalation_chain.py:1849/1880/1917 用例） | pass | 0/6 | - |
| chain-choice-payload-executes | 链成功路径 payload 型 choice 真实生效：closed 出口在 _close_chain_success 前执行注册表 choice（revise_scenario_reverify 带载荷→执行器完成成对写回等载荷动作、逐动作 DISPOSITION 记录落账、链闭环事件在执行成功后写）；执行机器单源（core/admin_choice_exec.py 模块级函数，人工 alert-resolve/直接路径/链路径三处同源，不复制分支逻辑）由独立结构探针直测委托关系（specs/escalation-chain/spec.md「payload 型 choice 链上生效」；core/admin_choice_exec.py:20/234、core/pm_engine/escalation_chain.py:917-947 closed 出口执行、tests/test_escalation_chain.py:2037 用例） | pass | 0/4 | - |
| chain-choice-failure-fails-closed | choice 执行失败/跳过不伪造闭环：执行器报错（载荷非法/异常）时不写 chain-closed 事件、不按成功闭环处理——chain-choice-failed 事件留痕（含执行错误与 run_id）、计一次失败按链既有失败语义处理（重试/转单/上升）；requires_payload 选项缺载荷时 skip not-ok 同款 fail-closed（specs/escalation-chain/spec.md「choice 执行失败不伪造闭环」；core/pm_engine/escalation_chain.py:924-946 fail-closed 分支、tests/test_escalation_chain.py:2075/2098 用例） | pass | 0/3 | - |
| chain-choice-out-of-allowlist-hands-off | 白名单外 choice 保持转单：admin 产出预算/豁免类人类拍板面 choice（注册表 allowlist 之外）时不执行 choice，按既有越界复核转单 Arbiter（不计失败），final 记录照常落账（specs/escalation-chain/spec.md「白名单外 choice 保持转单」；core/pm_engine/escalation_chain.py:892-916 越界复核先行、tests/test_escalation_chain.py:2115 用例） | pass | 0/2 | - |
| chain-event-runid-structure | 链事件携带 admin run id 结构字段：chain-closed/chain-handoff 等 admin 相事件的 run_id 落实际 admin run id（Arbiter 相事件语义不变），可供孤儿看护按 run_id 精确联查；chain_events_for_run 查询口按 kind+run_id 过滤（空 run_id 零命中、跨 run 隔离、arbiter 相事件不命中），台账损坏/缺失按零命中 fail-open；独立探针直测查询口过滤与降级（specs/escalation-chain/spec.md「链事件 run_id 可查」；core/pm_engine/escalation_chain.py:875-882 写侧结构字段、1261-1288 查询口、tests/test_escalation_chain.py:1927 用例） | pass | 0/4 | - |
| orphan-attribution-success-subtype | 孤儿升级归因读 result success 子型：run 文件末事件 type=result subtype=success（复刻首例事件 6474 形态）时告警 description 归因段为「处置结论成功但 final 处置记录缺失（落账缺口或收尾中断）——先核对处置台账与链事件再定处置」族文案，evidence 照常附终态摘录，不出现「非成功结论」字样；升级行为不变（人工仍知情）；独立探针直测归因文案分派与死因不明兜底（specs/human-escalation-alerts/spec.md「success 子型归因」；core/admin_monitor.py:6817-6830 result 分支读子型、tests/test_admin_disposition_reschedule.py:826 用例） | pass | 0/4 | - |
| orphan-attribution-non-success-unchanged | 非 success 子型归因文案回归锚：type=result 子型非 success（如 error_max_turns）时保持既有「run 以 result 终态退出但处置未完成（非成功结论）」文案不回退；frozen-terminated/cancelled/error/gate-blocked 各终态映射词表不受新分支波及（specs/human-escalation-alerts/spec.md「非 success 子型文案不变」；core/admin_monitor.py:6830 非 success 分支、tests/test_admin_disposition_reschedule.py:836/632 用例） | pass | 0/3 | - |
| orphan-reconcile-chain-closed | 链已闭环的孤儿 pending 不升级：pending 超时 + run 文件 result 终态 + 链痕抑制未命中、但链事件台账存在该 run_id 的 chain-closed 事件（复刻首例事件 6474 时间轴）时，不产生 escalation 告警——补写非 pending 终结 DISPOSITION记录闭合该 pending（status/result=resolved、admin_run_id 落该 run id、actions_taken 注明「由看护对账补记」），二轮巡检不再重判（specs/human-escalation-alerts/spec.md「链已闭环的孤儿 pending 不升级」；core/admin_monitor.py:6633-6658 对账兜底分支、tests/test_admin_disposition_reschedule.py:870 用例） | pass | 0/2 | - |
| orphan-reconcile-chain-handoff | 链 handoff 事件同样兜底：pending 超时且链事件台账存在该 run_id 的 chain-handoff 事件（admin 转单后 final 记录因历史缺口缺失的形态）时，同样对账终结不升级（specs/human-escalation-alerts/spec.md「链 handoff 事件同样兜底」；core/admin_monitor.py:6633-6658、tests/test_admin_disposition_reschedule.py:873 用例） | pass | 0/2 | - |
| orphan-reconcile-corrupt-fail-open | 链台账查询异常 fail-open：台账文件损坏（非法 JSON）/缺失时按零命中放行——孤儿升级照常发生（宁多告警不漏告警，对齐链痕抑制既有降级口径）；链缺席同款 fail-open 回归锚（specs/human-escalation-alerts/spec.md「查询异常 fail-open」；core/admin_monitor.py:6740-6757 联查门、core/pm_engine/escalation_chain.py:1286-1288 异常兜底、tests/test_admin_disposition_reschedule.py:876 用例） | pass | 0/3 | - |
| escalation-chain-regression-anchor | 触及面整体回归锚：链机器（tests/test_escalation_chain.py 全量——既有验收场景 S1-S15、首例时间轴、deferred 让行/frozen 预检族）与看护（tests/test_admin_disposition_reschedule.py 全量——链痕抑制/归因/reschedule 族）两文件 91 用例全绿，台账闭合与 choice 执行改动不回退既有链语义（impl 申报基线 58+33 passed；tests/test_escalation_chain.py、tests/test_admin_disposition_reschedule.py） | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 14 个（第 1 轮）。

- 首轮写入 14 个场景


# Proposal: admin-awaken-inflight-claim-guard

## Why

2026-11-14 复核窗实锤：windows-native-support 的两条 spec_amendment_inflight 观察型预警（指纹 d686660e6ab1 / 9a08ceaed5c8，同 kind 不同指纹，后者提交集 0e0c67d68+8e712ff69）18 秒内先后唤起两条 admin run（admin-windows-native-support-1794503555、-1794503573），span 重叠约 3.07 分钟、两条 run 合计约 8 分钟重复处置。本例结论相同零损害，但真并发实锤了竞态敞口——结论分歧将对同 spec 形成二次处置扰动。

回源核实：根因比「缺守卫」深一层。同 spec 在飞守卫已存在（core/admin_monitor.py:1286 _spec_has_active_admin_run、:6356 _has_active_admin_run_for_spec，spec 单键宽口径；窄口径 (spec, signal_type) 已被 fix-admin-cross-type-duplicate-dispatch 实证删除并注释在案），真正缺口是判定与标记异时点的 TOCTOU：互斥守卫在摄取线程提交前检查（core/admin_monitor.py:4271），而在飞标记（pending DISPOSITION）迟至共享池 worker 真正启动才落库（core/agent_runner/maintenance_runs.py:489-522）。本例两条唤起到实际启动之间有 23 分钟 / 8 分钟排队时延（共享线程池 fenixd.py:765 max_workers=2），第二次唤起过守卫时 pending 记录尚不存在，放行后两 run 并发。

家族复发三例：2026-11-03 fix-escalation-freeze-vs-parallel-admin-race（归档，冻结 vs 并行唤起竞态）、2026-11-13 deferred-resume 复活派发不重检（升级链面；fix-escalation-chain-watchdog-yield-gaps 已于 2026-11-16 归档，其承接面为「deferred 让行无唤醒静默挂起」与孤儿看护链痕让行，「复活派发不重检」面未见显式承接——属升级链域独立缺口，本能力不建设、如实登记另行立项）、本例（告警摄取面，本 SPEC 承接）。

## What Changes

- 提交点二次复查：_invoke_administrator 提交段（submit 入队前；admin 派发唯一投递点）再查一次 _has_active_admin_run_for_spec(spec)，命中则走既有 _persist_skipped_disposition（mutex-skip）并 return False——保持「未送达」语义，使 spec_amendment_inflight 的指纹备忘回滚（成条预写/未送达回滚：core/admin_monitor.py:5116-5122、:6059-6063）生效、冷却期满后可再成条。复查带双前置门（评审补定）：仅自动通道（signal_rec 非空；invoke_manual 以 signal_rec=None 直调 :8221，豁免）且 spec 非空（spec=None 的 daemon 级信号若复查，会因 _spec_has_active_admin_run 的 None 哨兵不过滤语义在任意在飞 run 期间被误让位，:6685-6690 在案）。
- 在飞标记前移（认领）：提交线程 submit 前同步登记进程内认领集合 _admin_dispatch_claimed_specs（锁保护，键=spec、值=属主令牌；复查与登记同锁原子，submit 抛出即回滚），worker 启动后落正式 pending DISPOSITION、结束（含异常）finally 按令牌释放认领键——把「在飞标记」从 worker 启动提前到提交点，单点同时收口摄取（admin_monitor.py:4333）与 _handle_signal（:5990）两条路的排队窗口。属主令牌为强制约定：run_administrator 为人工通道与同步回退共用（全仓直调仅 :8429 一处），按键无条件释放会误放他属认领。
- 明确不动面：人工通道 invoke_manual（admin_monitor.py:8143）不经互斥保持原样（用户显式呼叫是合法并行面）；arbiter 车道单飞队列自治不动；不同 spec 之间互不影响；被让位告警的自然恢复全部走既有机制（摄取让位不 mark_escalated、下一巡检周期自然重评、指纹备忘回滚、派发失败走 _retry_due_dispatch_failures、孤儿看护兜底）——零新增恢复逻辑。
- 单测覆盖「并发唤起 × 排队窗口 × worker 失败」矩阵（见 tasks.md）。

## Impact

- core/admin_monitor.py：_invoke_administrator 提交段加复查与认领（约 30 行），不改指纹去重、告警生成、处置回写与 D2b 互斥既有行为。
- core/agent_runner/maintenance_runs.py：worker 侧认领释放钩子（约 10 行）。
- tests/test_admin_awaken_claim_guard.py：新增。
- 无破坏性变更：人工通道、跨 spec 并行、arbiter 自治、既有恢复链全部不变。
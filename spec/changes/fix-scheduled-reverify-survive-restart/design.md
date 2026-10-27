# Design: fix-scheduled-reverify-survive-restart

## Context

排程重验现状（以代码为准复核）：`core/pm_engine/verification/escalation.py:2554` `_schedule_scenario_repair_reverify`（由 pipeline.py 首次耗尽分支调用，pipeline.py:1859-1884）——首次场景修复预算耗尽时排程一次未来重验。该排程**已有两层结构化落盘**：① `threading.Timer` 内存定时器（准点主通道，重启即失）；② `_dispatch_backoff_until`（epoch 截止）经 update_spec 落 STATE（escalation.py:2667-2676 写点）+ pipeline.py 同步写 error 文本（「已排程重验（iso 时刻）」）与耗尽计数字段。到期消费双通道：定时器（主）+ `event_bus._recover_testing` 周期扫描兜底（escalation.py:43-48 头注明示：「daemon 重启后定时器丢失，靠 `_dispatch_backoff_until` 兜底……到期后 event_bus._recover_testing 周期扫描拾起」；经 `spec_is_undriven` 条件③ 出窗判定，admin_monitor.py:1245/1309）。真正缺口：**state_machine 全扫恢复路径不读该等待态**——`core/state_machine.py:3329-3342` TESTING 分支孤儿判定（testing + tester_run=null + 无在飞 run）直接重置 implemented（"Recovered from interrupted state: testing"），发生在周期扫描拾起之前，排程窗口被吞（10-27 17:58 实证，作废 18:22:58 排程）。同型守卫先例：`event_bus._ready_hold_blocks`（event_bus.py:672-707）已对 ready 恢复做「有意等待早退」（`_cancelled_hold` / `_dispatch_backoffed` 双闸），testing 恢复分支缺同等闸门。另：现有排程无来源标记字段，恢复路径无法把「排程重验等待」与锁冲突退避/instant-fail 退避/env 阻塞等其他 `_dispatch_backoff_until` 共用写点（backoff.py:142、escalation.py:329）区隔开。

与既有记忆族的关系：`fenixd-autorecovery-blind-spot`（恢复重置状态却不知存活的 resume 子进程）是同族问题的另一面——恢复路径的孤儿判定只看「tester_run 指针 + 在飞 run」，看不到一切不落该指针的等待态。本 SPEC 把排程等待态纳入该判定的可见集。

## Goals / Non-Goals

**Goals:**
- 排程重验跨重启存活：等待态不被误重置，到点重验被执行
- 恢复路径对真孤儿态的行为逐位不变

**Non-Goals:**
- 不改排程重验的触发条件与预算语义（那是 fix-judge-budget-counters-alignment 的辖域）
- 不做通用「testing 等待态」框架——只把排程重验这一种已实证被吞的等待态纳入恢复可见集（其他等待态出现时按同一模式扩展）
- 不改 restart_request/重链协议（`fenixd-restart-request-midchain-behavior` 既有语义）

## Decisions

- **D1 排程标记字段与截止字段同原子写，截止单源**：新增 `_reverify_pending`（bool）+ `_reverify_reason`（来源信号短串）由排程写入点（`_schedule_scenario_repair_reverify`）与既有 `_dispatch_backoff_until` **同一原子写**落盘；到期判据**单源复用 `_dispatch_backoff_until`**，MUST NOT 另立 `_reverify_scheduled_at` 之类第二截止字段（恢复判定、`spec_is_undriven` 条件③ 探测静默、`_process_queue` 派发门读的是同一字段，双源必然漂移）。清零点 = 重验执行落定（verified/bug-found）+ 人工解冻（复用 unfreeze_spec 清零集，state_machine.py:2281，同原子写）+ 恢复路径拾起时；三处清零集 MUST 同步清 `_reverify_pending`/`_reverify_reason` 与仍未来的 `_dispatch_backoff_until` 残留。
- **D2 恢复判定前置检查（以标记字段为门）**：state_machine 恢复路径 TESTING 分支孤儿判定前读 `_reverify_pending`——未到期（`_dispatch_backoff_until` 未过）→ 跳过重置（保持 testing，日志 INFO 留痕「排程重验等待中」）；已到期 → 同样保持 testing 不重置，仅清排程标记，由既有周期扫描拾起（`spec_is_undriven` 条件③ 已出窗 → 判无驱动 → `_recover_testing` 重触发 verify，最坏延迟一个 poll_interval——无须恢复路径自行派发，取实现最短路径）。前置检查 MUST NOT 裸读 `_dispatch_backoff_until` 作门：该字段被锁冲突退避（backoff.py:142）、env 阻塞（escalation.py:329）、instant-fail 退避等多机制共用，裸读会把非排程等待态也纳入「不重置」豁免，改变真孤儿态既有行为（回归）。
- **D3 调度消费零新增**：到期消费复用既有 `event_bus._recover_testing` 周期扫描兜底（escalation.py:43-48 既有设计），不新起内存定时器、不新增扫描实现，天然抗重启；MUST NOT 误引 `check_scheduling_deadlines`（其只覆盖 drafted/ready 拾取，testing 态不在覆盖范围——escalation.py:47 头注既有警示）。
- **D4 与 autorecovery 盲态族的关系**：本 SPEC 不修「恢复不知存活 resume 子进程」（另一既有记忆缺口），只保证排程等待态不被恢复吞掉；两者恢复路径同函数，实现时须注意改动面仅限前置检查，不扰动既有判定顺序。

## Risks / Trade-offs

- **排程字段泄漏**（重验执行后字段未清）→ 恢复路径永远跳过重置、testing 悬挂：D1 的清零点写进解冻/verdict 落定两处 + 恢复拾起时同写清除，三重覆盖；单测覆盖「重验完成后字段已清」。
- **恢复触发与周期扫描双触发重验**：恢复路径到期分支只清标记不派发（D2），实际派发单源走 `_recover_testing`；`_enqueue` 按 (spec, agent_type) 去重与 `_dispatch_backoffed` 门兜底，幂等。
- **双截止字段漂移**（若实现另立 `_reverify_scheduled_at`）：恢复判定读其一、派发门/探测器读另一，互斥误判（等待期被派发 / 完成后被陈旧窗口阻塞）→ D1 单源约束消解，tasks 1.1 落为硬条款。
- **前置检查误豁免真孤儿态**（裸读共用退避字段所致）→ D2 以 `_reverify_pending` 标记为门；tasks 2.2 增非排程退避等待的回归用例。

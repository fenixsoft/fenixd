# 排程重验跨重启存活

<!-- knowledge: capability=scheduled-reverify-restart-durability rev=1
     sources=spec/archive/2026-10-30-fix-scheduled-reverify-survive-restart -->

验证链排程的未来重验（场景修复预算耗尽后安排的一次重验）以 STATE 结构化字段持久化：daemon 重启后恢复路径不把「合法等待排程重验」的 testing 态误吞成孤儿态，到点重验照常执行，不依赖内存定时器。

## 规则

- **排程三字段同一原子写落盘**：排程重验的截止时刻单源复用既有共用退避字段 `_dispatch_backoff_until`（epoch 秒），来源标记 `_reverify_pending`（bool）与 `_reverify_reason`（来源信号短串，如 scenario_repair_exhausted）由排程写入点（`escalation._schedule_scenario_repair_reverify`）与截止字段在同一原子写内落盘；MUST NOT 仅存在于 error 文本或进程内存，MUST NOT 另立与 `_dispatch_backoff_until` 并存的第二截止字段——恢复判定、探测静默（`spec_is_undriven` 条件③）、派发退避门读的是同一字段，双源必然漂移。字段名单点定义于 state_machine，禁裸串。
- **恢复路径豁免以标记字段为门**：daemon 全扫恢复路径（`recover_interrupted` TESTING 分支）孤儿判定前先读 `_reverify_pending`；MUST NOT 裸读 `_dispatch_backoff_until` 作门——该字段被 dispatch 锁冲突退避、instant-fail 退避、env 阻塞升级等多机制共用，裸读会把非排程等待态也纳入「不重置」豁免，真孤儿态行为回归。
- **未到期排程不吞**：标记在、截止未过 → 保持 testing 不重置（不写 "Recovered from interrupted state"）、三字段原样保留；到点重验由既有 `event_bus._recover_testing` 周期扫描兜底消费（读 STATE 截止字段，重启后照常执行，MUST NOT 依赖内存定时器——内存定时器只是准点主通道）。
- **到期未执行交周期扫描拾起**：截止已过（含截止缺失/不可解析的 fail-open：不可判定的截止视同已到期，等待它会让 testing 悬挂）→ 保持 testing 不重置，仅清排程标记与截止残留，交既有周期扫描拾起（`spec_is_undriven` 条件③ 已出窗，最坏延迟一个 poll_interval）；恢复路径 MUST NOT 自行派发——派发单源走 `_recover_testing`，由 `_enqueue` 按 (spec, agent_type) 去重与 `_dispatch_backoffed` 派发门兜底幂等。
- **清零点三处、同一原子写成对清**：① 重验执行落定（verified/bug-found）；② 人工解冻（`unfreeze_spec` 清零集）；③ 恢复路径拾起。三处经单点清零集 `REVERIFY_STATE_RESET_FIELDS` 同步清 `_reverify_pending`/`_reverify_reason` 与仍未来的 `_dispatch_backoff_until` 残留——只清标记不清截止会把已收口 spec 留在探测静默/派发退避窗内；标记泄漏未清会让恢复路径永远跳过重置、testing 悬挂。
- **门只作用于 TESTING 分支**：排程字段存在但 spec 非 testing 态时，不影响其他状态机转换（恢复照常重置、bug-found 等合法转换不受阻）。
- **真孤儿态行为不变**：testing 无排程标记且无在飞 run → 维持既有恢复行为（重置 implemented + "Recovered from interrupted state: testing"）。

## 溯源

- 2026-10-30 fix-scheduled-reverify-survive-restart（spec/archive/2026-10-30-fix-scheduled-reverify-survive-restart） — 新增本能力：排程三字段同原子写持久化（截止单源复用 `_dispatch_backoff_until`）、恢复路径 TESTING 孤儿判定前置排程等待门（标记为门、到期/损坏截止 fail-open 清标记交扫描）、三处清零单点集（动因：judge 修复预算耗尽排程 18:22 重验，daemon 重启后全扫恢复误判孤儿态重置 implemented，排程作废并额外烧一轮 stage2）

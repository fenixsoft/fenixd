# Design: fix-scheduled-reverify-survive-restart

## Context

排程重验现状：`core/pm_engine/verification/escalation.py:2687-2733` `_escalate_scenario_repair_exhausted` 一带——首次场景修复预算耗尽时排程一次未来重验，排程时刻只出现在 error 文本与升级告警（"已排程重验（2026-10-27T10:22:58+00:00）"），无独立结构化字段；到点执行依赖 daemon 进程内调度。daemon 重启（restart_request/pushed 链/崩溃自愈皆可能）后新实例全扫，恢复路径（"Recovered from interrupted state: <status>" 的产生点，`grep -rn "Recovered from interrupted state" core/` 定位）只见 testing + tester_run=null + 在飞 run 已归档 → 误判孤儿态重置 implemented，排程作废（10-27 17:58 实证，作废的是 18:22:58 排程）。

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

- **D1 结构化字段落 STATE**：`_reverify_scheduled_at`（ISO8601 UTC）+ `_reverify_reason`（来源信号短串），由排程写入点与升级/解冻清零同一原子写维护；清零点 = 重验执行完成（verified/bug-found 落定）+ 人工解冻（复用 unfreeze_spec 清零集，同原子写）。
- **D2 恢复判定前置检查**：恢复路径孤儿判定前读排程字段——未到期 → 跳过重置（保持 testing，日志 INFO 留痕「排程重验等待中」）；已到期 → 直接触发重验（走既有 implemented→testing 验证派发等价路径，或直接保持 testing 由周期扫描拾起，取实现最短路径）并清排程字段防重复触发。
- **D3 调度消费读 STATE**：周期扫描（全扫已每轮跑）在扫到 testing + 排程字段到期 + 无在飞 run 时触发重验——不新起内存定时器，天然抗重启。
- **D4 与 autorecovery 盲态族的关系**：本 SPEC 不修「恢复不知存活 resume 子进程」（另一既有记忆缺口），只保证排程等待态不被恢复吞掉；两者恢复路径同函数，实现时须注意改动面仅限前置检查，不扰动既有判定顺序。

## Risks / Trade-offs

- **排程字段泄漏**（重验执行后字段未清）→ 恢复路径永远跳过重置、testing 悬挂：D1 的清零点写进解冻/verdict 落定两处 + 恢复触发时同写清除，三重覆盖；单测覆盖「重验完成后字段已清」。
- **恢复触发与周期扫描双触发重验**：D2 触发时即清字段 + 在飞互斥（既有派发守卫）兜底，幂等。

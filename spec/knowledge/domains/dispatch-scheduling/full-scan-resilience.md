<!-- knowledge: capability=full-scan-resilience rev=3 sources=spec/archive/2026-09-02-fix-dispatch-orphan,spec/archive/2026-09-22-fix-orphan-ready-recovery-liveness,spec/archive/2026-09-29-evo-alert-noise-governance -->

# 全量扫描兜底恢复

full_scan 的单条异常隔离与孤儿 ready 的白名单恢复：毒条目不中止整轮扫描，无人驱动的 ready SPEC 获得短周期兜底重派。

## 现行规则

- 单条隔离：full_scan 的 recovery 循环与 check_blockers 阶段对单条 SPEC 的处理做独立异常捕获——任一 SPEC 处理抛出异常时记录 error 日志并继续处理其余 SPEC，整轮扫描不因单条异常中止。
- 每轮扫描输出 handled 与 failed 统计日志。
- 孤儿 ready 恢复走白名单判据：存在存活的 agent attempt 进程或未超时的活跃 worktree 锁才跳过；带 error 的 ready、有历史 run 记录但当前无活跃运行的 ready 均重新派发；重派发前清除 error 字段并保留 implementer_run 历史值。
- 恢复入口在清 error/重派之前复核 STATE 条目 `frozen`：为 True 时跳过恢复与重派并记 INFO（含 spec 名与跳过原因），不重放「派发→闸门拦截→冻结」流程；复核先于任何 STATE 写入（该入口仅在 error 非空时写 STATE，早退天然零写入），早退条件同步登记于入口 docstring 的早退清单。冻结 spec 的人工重派须先解冻，恢复链不代为放行。
- worktree 下仍有匹配的存活 claude agent 进程时，本轮跳过派发并记「skip: live child present」级日志，不做状态重置。
- 恢复动作除全量扫描外另有短周期精触发：daemon 在既有周期计时段（秒级粒度，不长于 60 秒）中对当前处于 ready 的 SPEC 执行一次恢复；精触发复用与 full_scan recovery 同源的恢复入口与判据，不另立判据或第二实现点。孤儿 ready 的恢复延迟上限为一个精触发周期（缺省 60 秒），而非一个 `schedule.poll_interval_minutes` 周期；周期扫描仍为兜底，语义不变。
- 精触发不放宽任何派发闸门：依赖 / 预算 / 内容完整性 / 冻结 / `start_after` / 退避 / 秒挂冷却 / 冷却去重全部照常生效——精触发只是把既有判据跑得更勤。
- 无需恢复的 ready SPEC（error 字段已为空且被判存活或有意等待）零 STATE.md 写入，不因周期变密产生稳态写放大。
- 「有意等待」显式包含派发退避期（`_dispatch_backoff_until` 未到期）与人工取消保持（`_cancelled_hold`）：精触发对二者在入口早退，不清空 error（error 承载退避原因，须保持可观测）、不触发重派发日志；早退复用既有判定（`Dispatcher._dispatch_backoffed` 与既有 `_cancelled_hold` 标记），判定异常时 fail-open（不早退），保底恢复不被新闸门吞掉。
- 退避到期后（`_dispatch_backoff_until` 已成过去时刻）精触发按常规恢复路径处理，早退闸门不使其永久失去恢复机会。
- 精触发的逐条处理保持单条异常隔离：单条异常捕获记日志，其余 ready SPEC 照常处理，不中断本轮精触发或影响 daemon 主循环。

## 溯源

- 2026-09-02 2026-09-02-fix-dispatch-orphan（spec/archive/2026-09-02-fix-dispatch-orphan） — 新增全量扫描单条隔离与 handled/failed 统计；孤儿 ready 恢复跳过条件由黑名单（有 error 或有 implementer_run 即跳过）改白名单，带 error 与带历史 run 的孤儿 ready 获得重新派发。
- 2026-09-22 2026-09-22-fix-orphan-ready-recovery-liveness（spec/archive/2026-09-22-fix-orphan-ready-recovery-liveness） — 孤儿 ready 恢复增加 60 秒级精触发（与 full_scan recovery 同源入口，恢复延迟从最坏 30 分钟降到 60 秒），并补退避期/取消保持入口早退、稳态零写入与逐条异常隔离约束。

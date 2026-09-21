# Spec Delta: full-scan-resilience

## MODIFIED Requirements

### Requirement: 全量扫描单条隔离

full_scan 的 recovery 循环与 check_blockers 阶段 SHALL 对单条 SPEC 的处理做独立异常捕获：任一 SPEC 处理抛出异常时记录 error 日志并继续处理其余 SPEC，整轮扫描 MUST NOT 因单条异常中止。

#### Scenario: 单条毒条目不中断扫描

- **WHEN** 一次 full_scan 中某 SPEC 条目在处理阶段抛出 TypeError，其余 SPEC 合法
- **THEN** 其余 SPEC 的 recovery 动作全部完成，日志中出现该失败的 error 记录与 handled/failed 统计

#### Scenario: 扫描统计可观测

- **WHEN** 任一轮 full_scan 完成
- **THEN** 日志输出本轮 handled 与 failed 计数

### Requirement: 孤儿 ready 白名单恢复

full_scan recovery 对 ready SPEC 的跳过条件 SHALL 由黑名单（有 error 或有 implementer_run 即跳过）改为白名单（存在存活的 agent attempt 进程或未超时的活跃 worktree 锁才跳过）；带 error 的 ready 与有历史 run 记录但当前无活跃运行的 ready 均 MUST 被重新派发，重派发前清除 error 字段并保留 implementer_run 历史值。

本恢复动作 MUST 除全量扫描外另有**短周期精触发**，使「停在 ready 且无人驱动」的 SPEC 不必等待一个完整的全量扫描周期：

- daemon MUST 在既有的周期计时段（秒级粒度，不长于 60 秒）中对当前处于 `ready` 的 SPEC 执行一次该恢复动作；
- 精触发 MUST 复用与 full_scan recovery **同源**的恢复入口与判据，MUST NOT 另立判据或第二实现点；
- 精触发 MUST NOT 缩短或改变 `schedule.poll_interval_minutes` 的周期扫描语义（周期扫描仍为兜底）；
- 精触发 MUST NOT 放宽任何派发闸门（依赖 / 预算 / 内容完整性 / 冻结 / `start_after` / 退避 / 秒挂冷却 / 冷却去重全部照常生效）；
- 对**无需恢复**的 ready SPEC（error 字段已为空且被判存活或有意等待），精触发 MUST 零 STATE.md 写入——不得因周期变密而产生稳态写放大；
- 「**有意等待**」MUST 显式包含**派发退避期**（`_dispatch_backoff_until` 未到期）与**人工取消保持**（`_cancelled_hold`）：精触发对二者 MUST 在入口早退，MUST NOT 清空 `error`（`error` 承载退避原因，需保持可观测）、MUST NOT 触发重派发日志。该早退 MUST 复用既有判定（`Dispatcher._dispatch_backoffed` 与既有 `_cancelled_hold` 标记），MUST NOT 另立判据；判定异常时 MUST fail-open（不早退），保底恢复不被新闸门吞掉；
- 同一轮精触发的逐条处理 MUST 保持单条异常隔离（首条 Requirement 口径）。

#### Scenario: 带 error 的孤儿 ready 获得重新派发

- **WHEN** 某 ready SPEC error 字段非空、implementer_run 指向已结束的历史 run、进程表中无对应存活 claude 进程且锁表无登记
- **THEN** 该轮 full_scan 对其触发重新派发，error 清空，implementer_run 保留

#### Scenario: 存活子进程期间不重复派发

- **WHEN** 某 ready SPEC 的 worktree 下仍有匹配的存活 claude agent 进程
- **THEN** 本轮跳过派发并记录「skip: live child present」级日志，不做状态重置

#### Scenario: 孤儿 ready 由精触发在扫描周期内完成恢复

- **WHEN** 某 ready SPEC 在两次全量扫描之间变为孤儿（无存活子进程、无待派发门、error 非空），且其 status 未再变化（不产生任何 STATE 变化事件）
- **THEN** 系统 MUST 在不长于一个精触发周期（缺省 60 秒）内对其重新派发，MUST NOT 等到下一个 `schedule.poll_interval_minutes` 周期

#### Scenario: 精触发不产生稳态写放大

- **WHEN** 精触发逐条检查一个 error 字段已为空的健康 ready SPEC（例如正等待并发槽位）
- **THEN** 系统 MUST NOT 对该 SPEC 产生任何 STATE.md 写入或状态更新日志

#### Scenario: 有意等待的 ready 不被精触发误派

- **WHEN** 某 ready SPEC 处于 `start_after` 未到期、人工取消保持（`_cancelled_hold`）或派发退避期内
- **THEN** 精触发 MUST 按既有闸门跳过，MUST NOT 重新派发该 SPEC

#### Scenario: 退避窗口内不抹掉退避原因

- **WHEN** 某 ready SPEC 因 worktree 锁冲突进入派发退避期（`error` 记载「backoff until …」、`_dispatch_backoff_until` 未到期），精触发周期到达
- **THEN** MUST NOT 清空该 `error`、MUST NOT 产生 STATE.md 写入、MUST NOT 打印「orphan ready 已重触发」类日志；退避到期后 MUST 恢复既有重试/恢复路径

#### Scenario: 退避到期后早退闸门不吞掉恢复

- **WHEN** 某 ready SPEC 的 `_dispatch_backoff_until` 已成为过去时刻
- **THEN** 精触发 MUST 按常规恢复路径处理该 SPEC（早退闸门 MUST NOT 使其永久失去恢复机会）

#### Scenario: 精触发单条异常隔离

- **WHEN** 精触发处理某一条 ready SPEC 时抛出异常
- **THEN** 该异常 MUST 被捕获记日志，其余 ready SPEC 的处理照常完成，MUST NOT 中断本轮精触发或影响 daemon 主循环

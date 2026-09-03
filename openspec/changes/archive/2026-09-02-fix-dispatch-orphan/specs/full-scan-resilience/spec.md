# spec-full-scan-resilience

## ADDED Requirements

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

#### Scenario: 带 error 的孤儿 ready 获得重新派发
- **WHEN** 某 ready SPEC error 字段非空、implementer_run 指向已结束的历史 run、进程表中无对应存活 claude 进程且锁表无登记
- **THEN** 该轮 full_scan 对其触发重新派发，error 清空，implementer_run 保留

#### Scenario: 存活子进程期间不重复派发
- **WHEN** 某 ready SPEC 的 worktree 下仍有匹配的存活 claude agent 进程
- **THEN** 本轮跳过派发并记录「skip: live child present」级日志，不做状态重置

# ADR-275：停滞类判据数据源为 run 流内任务观测

date: 2026-10-14
status: accepted

## Context

impl run 缺少「自最近任务完成起 N 轮」的停滞维度：kill_early 在末位扩容判定点消费主树 tasks.md 的 remaining_tasks，而 worktree run 期间主树 tasks.md 恒静态，零进度读不出在飞停滞；latency 停滞预算只看往返时长与产物 mtime。实证事故中 run 被轮数上限击杀前 275 轮零任务完成，全程无任何在途预警信号。

## Decision

一切「任务进度停滞」类判据的数据源为 run 流内 TaskUpdate completed 观测（run_task_track 单点解析），MUST NOT 使用主树 tasks.md 口径——后者是静态快照语义，不承载在飞 run 的动态进度。观测与判定分离：停滞观测面只注记（WARNING + run_metrics），不参与续期/击杀判定，不与既有 kill_early、延迟停滞预算互相触发。观测面自身不得成为轮询开销放大器：流内计数沿增量位点缓存、仅在流文件变化时重扫，禁止每轮全量重扫 run 流（600 轮 run 上为 O(N²) IO）。

## Consequences

停滞维度获得真实动态口径，未来任何停滞类机制（含 kill_early 的口径修正）受此数据源选型约束；主树 tasks.md 定位于静态快照与收尾对账，不再被期待反映在飞进度。增量位点缓存成为轮询路径消费 run 流的强制实现义务，新观测点接入必须复用该缓存而非自行重扫。

# ADR-024：agent 派发线程化，事件循环零阻塞

date: 2026-09-02
status: accepted

## Context

agent 执行在调用线程内同步进行：启动即派发则 full_scan 阻塞到 agent 结束，watcher/事件循环永不启动，新 SPEC 无法被调度（自托管场景实证）；watcher 线程内派发同样阻塞该线程；并发上限 `max_concurrent` 名存实亡。

## Decision

- 每个运行一个 worker 线程执行 agent；派发调用启动线程后立即返回——启动 full_scan、watcher 事件、周期扫描任何路径派发 agent 都不阻塞调用方，事件循环持续运转。
- 并发上限以计数守卫 + 信号量语义落实，agent 完成后在 worker 线程 finally 中释放计数并继续处理队列，「verifier 紧跟 implementer」的时序在同档顺序中保持。
- 队列与活跃集合的读写加进程内锁；STATE.md 写入沿用既有 flock 文件锁；spec 级防重入守卫语义不变，线程化不改变并发去重。

## Consequences

- watcher 与调度常活，max_concurrent 从名义值变为实际并发，多 SPEC 可并行实现/验证。
- 代价是引入线程竞态面：共享队列/计数全程加锁，agent 结果处理与状态推进仍串行，调度时序变化以 finally 延续机制对冲。

# 调度与派发
> 最后更新：2026-09-29 11:27 UTC

调度与派发：并发槽位与优先级调度、队列老化、依赖唤醒与兜底恢复、即时唤醒信号与事件投递完整性。

## 能力页

| 能力页 | 简介 |
| --- | --- |
| [优先级并行调度](priority-parallel-scheduler.md) | SPEC priority 感知派发：高优先派、同档并行、档间宽松并发、不抢占 |
| [并行度配置](parallelism-config.md) | `agents.max_concurrent` 并行度语义、校验与 Dashboard 编辑 |
| [派发并发度调优](dispatch-concurrency-tuning.md) | 并发缺省值与模板推荐值、回归互斥前提与可回退性 |
| [派发队列老化治理](dispatch-queue-aging.md) | 等待时长等效提级防低优先级饿死 |
| [依赖满足后的派发唤醒](dispatch-dependency-wakeup.md) | 依赖转入接受态时定向重评并入队等待中的 dependents |
| [调度踢一脚（kick）信号](scheduling-kick-signal.md) | 清空定时/激活 SPEC 的即时唤醒文件信号：每 SPEC 一文件、如实回报、逐条消费、陈旧回收 |
| [全量扫描兜底恢复](full-scan-resilience.md) | full_scan 单条隔离与孤儿 ready 白名单恢复 + 60 秒级精触发 |
| [SPEC 事件投递完整性](spec-event-delivery-integrity.md) | 同状态行动性更新的事件补发、bug_found 重发幂等、半写读取防御 |

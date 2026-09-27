# ADR-073：SPEC 状态事件发布点收口 EventBus 状态 diff

date: 2026-09-12
status: accepted

## Context

SPEC 状态变化存在跨进程写入：daemon 状态机、dashboard 进程的 admin 处置/人工恢复、`freeze_spec` 直写 `status=blocked`。若在 `state_machine.update_spec()` 内做进程内回调发布事件，只能覆盖 daemon 自己的写入，跨进程写入（含人工冻结）全部漏发。EventBus 是 daemon 进程内唯一的全局观察者（2s checksum 轮询 STATE.md diff），天然站在所有写路径的下游。

## Decision

- 一切「SPEC 状态变化」类消费者（hook 引擎及后续同类机制）挂 EventBus `_dispatch_changes` 的状态 diff 处分发（`old_status != new_status` 即产生事件），不在 `state_machine` 写入口内做进程内回调。
- 代价是事件延迟 ≤ 2s（轮询周期）：状态事件的消费方是管理类动作（重启/提交/通知），延迟无感；同 spec 连续多次跳变被合并为 latest from/to，管理动作不依赖逐拍中间态，接受。
- daemon 停机窗口内的状态变化漏发为已知边界：终态转换由 daemon 进程自身完成，窗口极小，不补发。
- 分发线程只投递任务，动作在 daemon 进程内线程池并发执行，不阻塞状态机、不排队不持久化（进程重启丢失在途执行可接受）。
- 动作执行结果审计落盘（append-only jsonl），失败发站内告警，不重试（commit/push 类动作重试有幂等风险）。

## Consequences

- 新增状态变化消费者一律接入 EventBus diff 分发点，禁止把回调注入扩散到 `state_machine` 的调用点路径。
- 轮询合并语义要求消费者以「观察到的 from/to」为准，不假设中间态逐拍可达。

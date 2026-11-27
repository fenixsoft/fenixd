# 调度与派发
> 最后更新：2026-11-27 17:55 UTC+8

调度与派发：并发槽位与优先级调度、队列老化、依赖唤醒与兜底恢复、即时唤醒信号与事件投递完整性、秒挂冷却派发门控、派发前置 harness 可达性自检、回落角色凭据预检与首派发冻结（降级试呼取证、稳态边沿降噪、告警生命周期对齐与版本白名单全车道一致拦截）、外部直写 STATE 的 testing 跃迁即时派发、调度重试计数记账（连续失败递增与耗尽冻结转人工、解冻/管理复位清零覆盖、冻结陈述取真实计数、人工重推记账与达上限信号去重）。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [优先级并行调度](priority-parallel-scheduler.md) | SPEC priority 感知派发：高优先派、同档并行、档间宽松并发、不抢占 | 2026-10-03 04:59 |
| [并行度配置](parallelism-config.md) | `agents.max_concurrent` 并行度语义、校验与 Dashboard 编辑 | 2026-10-03 04:59 |
| [派发并发度调优](dispatch-concurrency-tuning.md) | 并发缺省值与模板推荐值、回归互斥前提与可回退性 | 2026-10-03 04:59 |
| [派发队列老化治理](dispatch-queue-aging.md) | 等待时长等效提级防低优先级饿死 | 2026-10-03 04:59 |
| [依赖满足后的派发唤醒](dispatch-dependency-wakeup.md) | 依赖转入接受态时定向重评并入队等待中的 dependents | 2026-10-03 04:59 |
| [调度踢一脚（kick）信号](scheduling-kick-signal.md) | 清空定时/激活 SPEC 的即时唤醒文件信号：每 SPEC 一文件、如实回报、逐条消费、陈旧回收 | 2026-10-03 04:59 |
| [全量扫描兜底恢复](full-scan-resilience.md) | full_scan 单条隔离与孤儿 ready 白名单恢复 + 60 秒级精触发 | 2026-10-03 04:59 |
| [SPEC 事件投递完整性](spec-event-delivery-integrity.md) | 同状态行动性更新的事件补发、bug_found 重发幂等、半写读取防御 | 2026-10-03 04:59 |
| [秒挂冷却全车道门控](instant-fail-cooldown-full-lane-gate.md) | 秒挂冷却按故障面门控（planner/verifier 派发与 admin spec 作用域唤起入闸、全局信号放行、跳过 INFO 留痕）与到期复诵翻倍（上限 3 次/封顶 2400 秒） | 2026-10-30 23:11 |
| [派发前置可达性自检](dispatch-precheck.md) | 派发前置 harness binary 可达性自检短路、`[harness-cli-unavailable]` 归因与升级信号豁免、PATH 缺陷自愈闭环（幂等追加 + restart_request、盲写门） | 2026-11-08 21:21 |
| [testing 跃迁即时派发](testing-dispatch-liveness.md) | 外部进程直写 STATE 的 testing 跃迁经 watch 通道秒级即时派发 verifier（复用 _recover_testing 恢复路径、零新增事件类型、无驱动判定与在飞互斥吸收幂等），与 60 秒精触发/30 分钟 full_scan 兜底三层共存 | 2026-11-25 19:48 |
| [派发预检全车道覆盖](dispatch-preflight-coverage.md) | 回落角色默认链凭据三值判定探针（不静默跳过、嗅探不可判定按 30 分钟 TTL 降级试呼取证）、回落链凭据 systemd.env 注入通道、回落首派发冻结与按角色单条告警（放行键兜底、解冻自动关告警）、探针稳态边沿发射与双发射点一致、lane_env 告警同判稳态不重开与超 24h 话术升级、版本白名单挂共享 spawn 前置段全车道一致拦截（DNS 连通预检排除不动） | 2026-11-27 17:55 |
| [调度重试计数记账](dispatch-retry-accounting.md) | `_retry_count` 连续失败递增与 `>=` 封顶冻结转人工、解冻/管理复位清零集覆盖、冻结陈述取真实计数（越限注明已越限）、人工重推 source 记账与 push_failed 信号去重 | 2026-11-17 08:56 |

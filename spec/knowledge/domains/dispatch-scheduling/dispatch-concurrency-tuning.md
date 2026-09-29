<!-- knowledge: capability=dispatch-concurrency-tuning rev=1 sources=spec/archive/2026-09-27-add-pipeline-throughput-governance -->

# 派发并发度调优

派发队列的并发槽位规模治理：缺省值、模板推荐值与回归互斥前提的统一口径。

## 现行规则

- 派发队列读取 `agents.max_concurrent` 决定并发槽位数，代码缺省值为 5。
- `.fenix/config.yaml` 显式配置任意值（如 3、4）时按配置值生效；代码缺省值变更不影响显式配置的优先级。
- `.fenix/config.template.yaml` 的推荐配置同步为 5，并附注释说明资源前提：worktree 磁盘占用、网关并发压力、回归锁串行化。
- 运行时项目 `.fenix/config.yaml` 的实际并发调整属人工运维步骤（写入运维文档并在 `.fenix/todo.md` 登记），不作为 tasks.md 门禁任务。
- 并发值可随时人工调回任意值（可回退性）。
- 并发上调不改变回归互斥语义：多个并发实现 run 同时到达收尾回归检查点时，full-suite.lock 主机级互斥使回归实际串行执行；锁等待上限 600s 与超时 skip 语义保持，无并发回归互踩。

## 溯源

- [2026-09-27 2026-09-27-add-pipeline-throughput-governance](spec/archive/2026-09-27-add-pipeline-throughput-governance/) — 并发缺省值与模板推荐值由 2 统一上调至 5（实现排队为全历史最大时间池），固化互斥前提（full-suite.lock 主机级回归锁）与可回退性；运行时调整定位为人工运维步骤。

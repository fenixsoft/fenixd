# dispatch-concurrency-tuning 能力增量（add-pipeline-throughput-governance）

> 并发槽位上调契约：`agents.max_concurrent` 代码缺省值与模板推荐值统一为 5，互斥前提（full-suite.lock）与可回退性固化。

## ADDED Requirements

### Requirement: 并发缺省值与模板推荐值统一上调

派发队列读取 `agents.max_concurrent` 的代码缺省值 MUST 从 2 上调至 5；`.fenix/config.template.yaml` 的推荐配置 MUST 同步为 5 并附注释说明资源前提（worktree 磁盘、网关并发压力、回归锁串行化）。运行时 `.fenix/config.yaml` 的实际调整为人工运维步骤（写入运维文档与 `.fenix/todo.md` 登记，不作为 tasks.md 门禁任务）。配置值 MUST 仍可随时人工调回任意值（可回退性），代码缺省值变更不影响显式配置的优先级。

#### Scenario: 无显式配置时生效 5

- **WHEN** 某项目 `.fenix/config.yaml` 未写 `agents.max_concurrent` 键
- **THEN** 派发队列按缺省值 5 并发实现 run；显式配置任意值（如 3）时按配置值生效

#### Scenario: 主机级回归锁互斥不变

- **WHEN** 5 个并发实现 run 中多个同时到达收尾回归检查点
- **THEN** full-suite.lock 主机级互斥使回归实际串行执行，锁等待上限（600s）与超时 skip 语义与现状一致，无并发回归互踩

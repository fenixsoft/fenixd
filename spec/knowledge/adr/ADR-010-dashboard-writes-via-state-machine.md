# ADR-010：Dashboard 状态写回统一经 StateMachine

date: 2026-09-02
status: accepted

## Context

Dashboard 是与 daemon 并存的独立进程，但具备对项目状态的写能力（清除 spec 错误字段、编辑配置等）。它与 daemon 对同一批状态文件并发读写，写路径若各自实现，绕过序列化与原子性会引入半写损坏与互相覆盖。

## Decision

- Dashboard 进程对 STATE.md 的任何写操作一律实例化 `StateMachine` 走 `update_spec` 等既有入口——复用其 flock 写序列化 + 临时文件原子 rename 语义，与 daemon 的写入处于同一把锁下。
- 对 `.fenix/config.yaml` 的写回同样只走既有写函数：受管键白名单合并（只更新受管键、其余键原样保留）+ 局部校验 + 临时文件 rename 原子落盘。
- 并发模型为全量重写、最后写者胜：写窗口微秒级且 Dashboard 写操作稀少，不为此新增锁设施。
- 幂等写（目标字段已是目标值）仍走完整写路径以刷新时间戳、触发下游刷新，不做短路。

## Consequences

- 新增 Dashboard 写能力时只需选择既有写入口，不需要（也不允许）自行打开状态文件写入。
- 最后写者胜意味着极端并发下存在互相覆盖的理论窗口——已被接受为架构级权衡；需要强一致的字段不应经由 Dashboard 高频写。
- 写后可见性依赖 watcher 的 mtime 监视推送与前端轮询兜底，写端点自身不做额外推送握手。

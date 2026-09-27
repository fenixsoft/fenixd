# ADR-030：dashboard 控制面以文件信号驱动 daemon

date: 2026-09-03
status: accepted

## Context

dashboard server 与 daemon 是分离进程，控制类动作（手动唤起 Administrator 处置、重启 daemon）需要跨进程传递。server 直接派发 agent 会绕过状态机与 token 预算；直接进程调用又引入新 IPC 设施。框架已有「信号文件 + 轮询拾取」的成熟先例（重启请求）。

## Decision

- server 不直接派发 agent、不直接操作 agent 生命周期：控制请求经存在性校验后原子落盘为约定路径的信号文件，daemon 主循环轮询拾取（读 → 删文件 → 走 daemon 内既有入口执行）。
- 信号文件即互斥与崩溃安全：文件存在即拒绝重复请求（409）；残留文件在 daemon 重启后仍会被消费，不丢请求。
- 执行侧一律复用 daemon 内既有机制——状态机转换、token 预算、prompt 构造、留痕通道，server 侧只做校验与转写，不复制任何执行逻辑。

## Consequences

- 跨进程控制零新增 IPC 设施，与既有进程管理方式同构，server 崩溃不产生半执行状态。
- 信号天然无回执确认，消费可见性依赖既有 watch/轮询通道；新增文件信号时必须同步裁定其消费方与确认通道，避免「写完没人读」的悬空信号。

# ADR-338：dsh 持久状态跨进程写通道单一化（web API + 官方 SDK，禁直写 registry）

date: 2026-11-09
status: accepted

## Context

fenixd daemon 需要在 dsh harness run 终态把会话标记归档（workspace registry 的 `archivedSessionIds`），未来同类需求（rename / pin / 分组等会话状态操作）可预期复现。候选路径三条：

1. headless 进程直写 `<dsh_home>/storages/workspace.json`——dsh-storage-json 明示无跨进程写锁（last-completion wins），直写与 web 进程内存缓存互相覆盖（丢更新、UI 不实时刷新）；
2. Python 侧手搓 `/api/remote.mux` 帧协议——Typert RPC InvocationDescriptor 编解码，自实现高风险；
3. daemon 子进程调用 Node helper，复用 `@deepseek-ai/` 官方 client SDK。

## Decision

任何非 web 进程对 dsh 持久状态（workspace registry 等 web 持有的存储）的跨进程变更，唯一通道 = dsh web HTTP API（API Gateway `/api/remote.mux`），协议帧由官方 client SDK 承载；daemon 以子进程调用 Node helper 完成，Python 侧不承担帧编解码。**严禁跨进程直写 registry 及手搓协议帧**——后续 SPEC 涉及 dsh 会话状态操作一律沿用本通道，另开直写或第二协议实现须显式 supersede 本 ADR。

豁免面：会话自有 header（如标题）属会话所属进程自有写路径，在 bundle 内进程内写（`rename()`）即可，不经 web API、不受 web 在线约束。

## Consequences

- dsh web 在线成为跨进程状态变更的前置；离线场景由持久化重试队列兜底（daemon 重启不丢、backoff 重试、放弃阈值封顶），卫生类收尾不得阻塞 run 主链路。
- 协议正确性单点收敛在官方 SDK：dsh 上游升级协议时只需升级 bundle 内 SDK 与 helper，daemon 零帧知识。
- 凭据面收敛为 `<dsh_home>/.credentials.yaml` 的 browser-session secret 经 `--secret-file` 传入 helper，daemon 不持有帧内鉴权逻辑。

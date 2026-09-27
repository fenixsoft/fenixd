# ADR-015：优雅退出快速排水并落 interrupted 终态标记

date: 2026-09-02
status: superseded
Superseded by: ADR-063(停机分规划性/非计划两档，恢复按 git 事实保全续做)

## Context

daemon 受外部 supervisor 管理：SIGTERM 后固定 60s 即 SIGKILL。若优雅退出逐个等待在跑 agent（每 agent 最长可达数百秒），只要 SIGTERM 时存在未完成 agent，daemon 必然被强杀——被中断的 run 无任何终态证据，下游孤儿检测将其误判为「疑似 daemon 崩溃」反复升级。关闭语义的方向须裁定：拉长 supervisor 窗口，还是让 daemon 秒级排水。

## Decision

- 关闭语义在 daemon 侧重写为快速 terminate 流程：先对全部在跑 agent 统一 SIGTERM → daemon 侧同步写入 interrupted 标记 → 统一等待固定短缓冲（约 10s）→ 存活者 SIGKILL 兜底。多 agent 并行处理，不做逐个串行等待；总关闭时长恒为秒级，远小于 supervisor SIGKILL 窗口。
- 不扩展 supervisor 窗口：等待不可控地串联叠加，且 agent 真卡死时等待无意义。
- interrupted 标记为 run 产物文件末行 `{"type":"interrupted","reason":"daemon shutdown",...}`：对所有 agent 车道统一生效，且单行原子追加不破坏 JSONL 结构。
- 下游孤儿检测先读 run 文件：含 interrupted 标记 → 追加 interrupted 终态记录终结该 run 且不升级；文件不存在或无标记 → 维持「疑似崩溃」升级兜底（宁多告警、不漏告警的保守方向）。

## Consequences

- daemon 重启不再触发 supervisor SIGKILL，被中断的 run 有可识别证据，「已知中断」与「疑似崩溃」在告警面上可区分、不再重复升级。
- interrupted 的 run 一律不得被下游视为 success；其产物可能截断，后续由 stuck/失败信号自然接管。
- daemon 在缓冲窗口内被外部强杀的极端情形无标记可写，按疑似崩溃升级——已知且保守的残留风险。

# agent-shutdown-interrupt Spec

## ADDED Requirements

### Requirement: 优雅退出时主动终止在跑 agent

daemon 收到关闭信号（SIGTERM/SIGINT）进入优雅退出时，SHALL 对所有尚未完成的在跑 agent 子进程主动发起 SIGTERM，且 SHALL NOT 等待 agent 自行完成（关闭流程不再有逐 agent 最长 300s 的等待窗口）。整体 agent 终止阶段 SHALL 在 10s 量级内完成，确保 daemon 在 supervisor 的 60s SIGKILL 窗口内正常退出。

#### Scenario: 关闭时有 agent 在跑

- **WHEN** daemon 关闭且存在未完成 agent（如正在运行的 impl/admin/verify）
- **THEN** 所有在跑 agent 收到 SIGTERM，daemon 在 ≤10s（缓冲窗口）内退出；总关闭时长不触发 supervisor 的 60s SIGKILL

#### Scenario: 已完成 agent 不受影响

- **WHEN** daemon 关闭时某 agent 已完成（run 已 finalize、进程已退出）
- **THEN** 该 run 不产生 interrupted 标记，结果保持最终状态

### Requirement: 被终止的 run 写入 interrupted 标记

对每个被终止的在跑 agent，SHALL 在其 run 文件（`.fenix/runs/<run_id>.jsonl`）末尾追加一条 `{"type": "interrupted", "reason": "daemon shutdown", "by": "agent_runner"}` 记录，用于将"已知中断"与"异常/崩溃"区分。

#### Scenario: 标记追加到 run 文件

- **WHEN** 在跑 agent 因 daemon 关闭被终止
- **THEN** 其 run 文件包含 type=interrupted 的记录；该记录按追加模式单行写入，不破坏既有 JSONL 行

### Requirement: 缓冲超时兜底 SIGKILL

向在跑 agent 发送 SIGTERM 后，SHALL 提供 ≤10s 的优雅缓冲窗口；窗口结束时仍未退出的 agent SHALL 被 SIGKILL 强制终止，且 run 文件的 interrupted 标记已写入。

#### Scenario: agent 未在缓冲内退出

- **WHEN** agent 收到 SIGTERM 后 10s 内未退出
- **THEN** agent 被 SIGKILL，进程终止，run 文件已含 interrupted 标记（标记不依赖 agent 是否优雅退出）

### Requirement: 多 agent 并行终止

存在多个在跑 agent 时，SHALL 一次性对所有 agent 发起 SIGTERM 与标记写入（并行，非串行逐个等待），使终止阶段总时长不随 agent 数量线性增长。

#### Scenario: 多个 agent 同时关闭

- **WHEN** daemon 关闭时有 3 个在跑 agent
- **THEN** 它们同时收到 SIGTERM，终止阶段总时长与单 agent 场景一致（≤10s 缓冲），非 3 倍时长
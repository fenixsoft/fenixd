# Spec Delta: agent-runner

## NEW Requirements

### Requirement: SIGTERM/SIGKILL 死法记录信号来源

agent_runner 捕获 CLI 子进程终结时，MUST 区分并记录死法来源：daemon drain（shutting_down/产物 interrupted 标记）→ 沿用 [shutdown-interrupted]；外部 kill（exit≠0 且非 daemon 关停，如 admin 处置 run 被外部 SIGTERM/SIGKILL）→ 归类为带信号来源标签的错误（如 [signal-kill: SIGKILL/143]），MUST 在 run 错误文本、日志与告警 evidence 中透出来源（尽力反查父进程/信号者，查不到标 unknown）；MUST NOT 一律归 [provider-transient]。

**背景（实测依据）**：2026-09-16 admin-refactor-dashboard-data-module-1789511370（Exit 143）与 admin-refactor-agent-runner-module-1789520256（Exit -9）两 run 内 [provider-transient] 27/12 次、[shutdown-interrupted] 0 次，无 cost 无来源记录。

#### Scenario: 外部 kill 带来源标签

- **WHEN** CLI 子进程以信号死法结束（143/-9）且非 daemon 关停场景
- **THEN** 错误文本含信号来源标签（kill/unknown），run 产物与告警 evidence 可追溯；不归 [provider-transient]

#### Scenario: daemon 关停仍走 shutdown 标记

- **WHEN** shutting_down 置位或产物 interrupted 标记存在
- **THEN** 维持 [shutdown-interrupted] 语义（不回归既有守卫）

### Requirement: 信号死法连续出现触发熔断冷却

Exit 143/-9 类（信号死法）失败 MUST 计入信号类熔断计数：连续出现（如阈值 3）时触发熔断冷却（复用/扩展 infra_breaker 或 provider_circuit 计数通道），冷却期内该链路不再无限重试；涵 admin/impl 处置 run 路由，MUST NOT 因瞬态通道而反复撞运气至预算耗尽。

#### Scenario: 143/-9 连发触发冷却

- **WHEN** 同一 spec/链路的信号死法失败连续达阈值
- **THEN** 熔断冷却启动（不再原地重试），告警登记，冷却到期自动恢复

#### Scenario: 正常瞬态不受影响

- **WHEN** provider 网络抖动类瞬态（非信号死法）
- **THEN** 既有退避重试不变

### Requirement: 非内容/非网关质量失败不进瞬态通道

产物硬门格式拒绝（如结果文件缺字段/非法 JSON 导致的 gate 拒绝）与信号死法 MUST NOT 被注入 [provider-transient] 通道；两类各自独立归类与计数，避免瞬态指纹污染与伪装重试。

#### Scenario: 格式拒绝独立归类

- **WHEN** 失败为产物硬门格式拒绝（非网关质量、非内容判定）
- **THEN** 不记瞬断指纹、不走瞬态重试，走 gate 既有重试/降级语义（注：task-gate 相关语义另由 fix-impl-tasks-completion-gate 指定，此处仅管归类通道隔离）
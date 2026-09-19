# 状态无驱动探测与恢复（orphaned-state-signal）

## 需求

### R1 无驱动判定
- AdminMonitor SHALL 在巡检中新增检测：spec `status ∈ {implementing, testing}` 且同时满足"无驱动"三条件时，判为 `orphaned_state`：
  1. **无活动 run 文件**：`.fenix/runs/` 下属于该 spec 的 run 文件 mtime 均超出宽限窗；
  2. **无存活 agent 子进程**：不存在对应 `impl-<spec>-` / `verify-<spec>-` 模式的存活进程；
  3. **无待派发**：无针对该 spec 的待处理派发/恢复挂起（如 transient backoff 未到期、暂存待拾取、`_cancelled_hold` 等有意等待态）。
- 三条件 MUST 同时成立才判无驱动；任一不成立（如长 run 仍在跑、进程仍存活、有意等待中）MUST NOT 判无驱动。

#### Scenario: 状态悬置且无人驱动
- **WHEN** 某 spec 处于 `testing`，其最近 run 文件 mtime 已超宽限窗、无 `verify-<spec>-*` 存活进程、无待派发
- **THEN** 产生 `orphaned_state` 信号

#### Scenario: 长 run 仍在跑不误报
- **WHEN** spec 处于 `testing` 且存在 mtime 在宽限窗内的 run 文件或存活 verifier 进程
- **THEN** 不产生 `orphaned_state` 信号

#### Scenario: 有意等待不误报
- **WHEN** spec 处于 `testing` 但存在 transient backoff 未到期、`_cancelled_hold=true` 或 start_after 定时未到
- **THEN** 不产生 `orphaned_state` 信号

### R2 阈值独立于 stuck
- `orphaned_state` 的持续时间阈值 SHALL 显著短于既有 `stuck` 阈值（`run_timeout_seconds + 600s`，当前 9000+600=9600s ≈ 160 分钟），默认约 10–15 分钟，使"状态无驱动"能在分钟级被发现而非等 160 分钟。
- 该阈值 MUST 单源可配（配置键缺省值合理），且与 `stuck` 阈值互不影响。

#### Scenario: 分钟级发现
- **WHEN** spec 悬置于 `testing` 无驱动超过该短阈值
- **THEN** 产生 `orphaned_state` 信号，早于 `stuck`（160 分钟）触发

### R3 恢复出口
- `orphaned_state` 信号经既有 Administrator 通道可唤起处置；处置完成后走既有复位直通道（`resolve_env_blocked_reset_path`：分支已合并 → `transition_gate(testing)` + verifier 入队重验；否则 → `ready`）。
- `core/event_bus.py` 的运行期恢复（`_recover_one`）SHALL 补齐 `testing` 态无驱动的出口：对 `testing` 且无活动 run/进程的 spec，MUST NOT 静默留白（补恢复动作或联动 `orphaned_state`）。
- `implementing` 态已有 recovery 分支，MUST NOT 破坏其既有语义。

#### Scenario: 无驱动 testing 有出口
- **WHEN** 运行期（非重启）某 spec 落入 `testing` 且无驱动
- **THEN** recovery/信号路径能发现并触发重派，无需等待 daemon 重启

### R4 信号登记与去重
- `SIGNAL_SEVERITY` MUST 登记 `orphaned_state`；`SIGNAL_RECOMMENDATION` MUST 登记处置指引。
- 同一 spec 同类信号 MUST 走既有 `escalation_cooldown_minutes` 节流，防重复唤起。

#### Scenario: 节流生效
- **WHEN** 无驱动状态持续并连续多轮巡检命中
- **THEN** 冷却窗内只唤起一次 Administrator

## 验收标准
- 单元测试：状态悬置 + 无 run + 无进程 → 产生信号；长 run 在跑 → 不产生；有意等待（`_cancelled_hold`/backoff/start_after）→ 不产生。
- 单元测试：恢复出口——`testing` 无驱动 spec 能被 recovery/信号路径发现。
- 回归：本事故场景（复位失败致 spec 悬置 testing）在新的分钟级阈值内被 `orphaned_state` 捕获（而非 160 分钟后的 `stuck`）。

# graceful-restart-drain 能力增量（add-pipeline-throughput-governance）

> 重启排水契约：排水窗口上限配置化并与 supervisor SIGKILL 宽限协调（消解 1800s vs 60s 错配），restart 触发时向在飞 run 广播 checkpoint 信号（best-effort）。

## ADDED Requirements

### Requirement: 排水窗口配置化与宽限协调

新增排水窗口配置项（如 `agents.run_drain_max_seconds`，代码缺省 60s），专管 daemon restart 流程等待在飞 run 排水的时长上限，超窗后按既有强杀路径收场；该值 MUST ≤ 既有 `admin.shutdown_drain_seconds`（缺省 1800）——supervisor 的 SIGKILL 等待 = `shutdown_drain_seconds + 120s` 余量（`bin/fenixd_supervisor.py`，interrupt-recovery-preserve D2 起可配；并非固定 60s），满足该不等式即保证 supervisor 不会先于 daemon 排水窗口强杀。缺省组合下的「重启到新 daemon 就绪」总时长 MUST 显著短于现状（现状病根是排水上限 1800s 而在飞 run 多数不会窗内自行收尾，重启白等半小时；supervisor 侧等待为 drain+120s，非截断瓶颈）。常规停机仍走 `admin.shutdown_drain_seconds` 语义不变。配置 MUST 可人工调整（如调大给长排水留裕量），代码缺省变更不影响显式配置优先级。

#### Scenario: 缺省配置下重启快速收敛

- **WHEN** 触发 daemon restart（restart_request 信号）且存在 2 个在飞 impl run，二者均未在缺省排水窗口（60s）内自行收尾
- **THEN** daemon 等待至多 60s 后按既有路径强杀二者并完成重启，全程无 1800s 级空等；被杀 run 走既有恢复路径（保留分支续做）

#### Scenario: 显式调大窗口

- **WHEN** 运维将排水窗口配置为 600s 且触发 restart
- **THEN** daemon 等待在飞 run 至多 600s；窗口内自行收尾的 run 正常完成、不被强杀

### Requirement: restart 前广播 checkpoint 信号

restart 触发、停止新派发后，daemon MUST 向每个在飞 run 广播一次 checkpoint 信号（写 run 控制文件；implementer 侧已有响应语义的按既有语义尽快落盘进度声明收尾，无响应语义的 best-effort 忽略）。广播 MUST NOT 阻塞排水等待（写后即返回），MUST NOT 产生新的失败终态或打回；信号未读即被强杀的 run 按既有恢复路径处理，行为与现状一致。

#### Scenario: 广播促使尽快收尾

- **WHEN** restart 触发时某在飞 impl run 处于任务收尾阶段，收到 checkpoint 信号后 20s 内完成结果文件落盘并退出
- **THEN** 该 run 在排水窗口内正常收工，其成果按正常路径合并判定，不被强杀

#### Scenario: 广播零副作用

- **WHEN** 某 run 不识别 checkpoint 信号（无响应语义）且最终被超窗强杀
- **THEN** 其处理与未广播时完全一致（保留分支恢复续做），无新增告警、无状态损坏

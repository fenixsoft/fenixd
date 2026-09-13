## ADDED Requirements

### Requirement: 代码陈旧检测的持续状态与可观测性

daemon MUST 把「进程内运行的代码相对磁盘已更新」（陈旧）从一次性事件升级为**持续状态**：每个检测周期（既有 30s 配置热更新检测点）重新比对 `fenixd.py` 与 `core/**/*.py` 的最大 mtime 与进程启动时记录的 baseline，并维护该状态，MUST NOT 仅在首次命中后永久静默。陈旧状态为真时，除既有 `fenixd.log` WARNING 外，daemon MUST 经 AdminStore 写入一条 `signal_type: stale_code` 的 escalation 告警，描述 MUST 说明「daemon 进程持旧代码，自愈将在连续空闲后触发重启」。该告警 MUST 为 `warning` 级：写入即自动标记已处理，MUST NOT 进入人工告警横幅/待处理队列，仅作历史记录保留（2026-09-13 用户降噪决策——陈旧属可自愈收敛的持续状态，无需人工介入）。告警写入 MUST 由状态边沿（假→真）触发，单个陈旧周期内 MUST NOT 重复堆积。状态转假时 MUST NOT 产生新的陈旧告警。

#### Scenario: 陈旧命中写入可见告警

- **WHEN** daemon 运行期间 `core/**/*.py` 的 mtime 超过进程启动 baseline
- **THEN** 日志出现陈旧 WARNING，且 `admin_alerts` 新增一条 `signal_type: stale_code`、`severity: warning`、`handled: true` 的告警记录，该状态在后续检测周期持续保持为真

#### Scenario: 告警不进人工待处理队列

- **WHEN** 陈旧命中写入 `stale_code` 告警
- **THEN** 该记录 `handled` 为真，MUST NOT 出现在 Dashboard 人工告警横幅与待处理列表中（仅可在历史/已处理区查看）

#### Scenario: 单次陈旧周期不重复堆积

- **WHEN** 陈旧状态在多个检测周期持续为真（尚未转假）
- **THEN** 不新增第二条 `stale_code` 告警记录

#### Scenario: 重启后陈旧状态解除

- **WHEN** daemon 因自愈重启后重新启动，磁盘代码未再变化
- **THEN** 陈旧状态为假，不再产生新的陈旧告警，也不再触发自愈

### Requirement: 空闲感知的陈旧自愈触发

daemon 主循环 MUST 在陈旧状态为真、配置 `stale_code_selfheal.enabled` 为真、且项目存在活跃 supervisor 托管时，判定「空闲」；当空闲连续保持达 `stale_code_selfheal.idle_confirm_seconds`（默认 120 秒）后，MUST 写入 `.fenix/restart_request`（复用既有 supervisor 优雅重启协议，MUST NOT 引入新信号或改变该协议语义），并在日志中记录触发原因与等待时长。空闲计时 MUST 在任一非空闲信号出现时立即清零。`.fenix/restart_request` 已存在时 MUST NOT 重复写入。

#### Scenario: 连续空闲达标触发重启

- **WHEN** daemon 处于陈旧状态且配置启用，项目受 supervisor 托管，连续 120 秒无活跃 run 与在途处置
- **THEN** `.fenix/restart_request` 被写入，日志记录「陈旧自愈触发」及等待时长，supervisor 随后执行优雅重启

#### Scenario: 出现活跃任务则空闲计时清零

- **WHEN** 陈旧状态为真且已连续空闲 90 秒，此时一个新 run 被派发
- **THEN** 空闲计时清零，MUST NOT 写入 `restart_request`；该 run 收口后须重新累计满 120 秒才触发

#### Scenario: 重启已在途时不重复写入

- **WHEN** `.fenix/restart_request` 已存在（重启在途或因其他原因被写入）
- **THEN** 自愈 MUST NOT 再次写入该文件，也不产生重复日志

#### Scenario: 未受托管项目不自愈

- **WHEN** 项目托管态为 `unmanaged`（daemon 在跑但无 supervisor），且代码陈旧、已连续空闲超过阈值
- **THEN** MUST NOT 写入 `.fenix/restart_request`（写了也无人消费），陈旧告警维持，等待经 Dashboard「安装托管」或 `/fenix-setup` 恢复托管

#### Scenario: 配置关闭时不自愈

- **WHEN** `stale_code_selfheal.enabled` 为 `false`，代码陈旧且长期空闲
- **THEN** MUST NOT 写入 `restart_request`，但陈旧状态与告警 MUST 仍然产生，日志 MUST 明示自愈已被配置关闭

### Requirement: 空闲判定语义

「空闲」MUST 定义为**同时**满足：`agent_runner` 无活跃 run（覆盖 planner / implementer / verifier / judge 全部 run 形态）与 admin 处置 worker 池无在途任务。任一来源非空即 MUST 判定为非空闲。判定 MUST 复用既有内部状态（如 `_active_runs`），MUST NOT 通过扫描外部进程列表反推。

#### Scenario: 活跃 run 期间判定为非空闲

- **WHEN** 存在任一进行中的 agent run（含 planner 出题、verifier 验证）
- **THEN** 空闲判定为假，不计入连续空闲时长

#### Scenario: admin 处置在途判定为非空闲

- **WHEN** 无 agent run 活跃，但 admin 处置 worker 池有在途任务
- **THEN** 空闲判定为假，不计入连续空闲时长

#### Scenario: 双源皆空判定为空闲

- **WHEN** 无 agent run 活跃且 admin 处置池无在途任务
- **THEN** 空闲判定为真，开始累计连续空闲时长

### Requirement: stale_code_selfheal 配置与界面

系统 MUST 支持 `stale_code_selfheal` 配置节，含 `enabled`（布尔，缺省 `true`）与 `idle_confirm_seconds`（整数秒，缺省 `120`）。配置缺失或键非法时 MUST 回退缺省值且不使 daemon 启动失败。配置 MUST 走既有 30s 配置热更新，改动 MUST 在下一检测周期生效而无需重启 daemon。Dashboard 设置页 MUST 提供该节的可读写界面（遵循「新增配置项必须带界面」的既有约束），展示项 MUST 与配置文件键一一对应。

#### Scenario: 缺省值生效

- **WHEN** 配置文件中不存在 `stale_code_selfheal` 节
- **THEN** 自愈按 `enabled: true`、`idle_confirm_seconds: 120` 运行

#### Scenario: 非法值回退不中断

- **WHEN** `idle_confirm_seconds` 被写成非整数或负数
- **THEN** daemon 回退到缺省 120 秒，不抛异常、不中断主循环

#### Scenario: 热更新立即生效

- **WHEN** 用户在运行中的 daemon 上把 `enabled` 改为 `false`
- **THEN** 下一检测周期起不再触发自愈，无需重启 daemon

#### Scenario: 设置页可读写该节

- **WHEN** 用户在 Dashboard 设置页查看 `stale_code_selfheal` 一节
- **THEN** 界面展示 `enabled` 与 `idle_confirm_seconds` 的当前值，修改保存后写回配置文件

### Requirement: supervisor 启动失败熔断

`bin/fenixd_supervisor.py` MUST 记录每次 daemon 启动后的存活时长；当 daemon 在启动后 60 秒内即退出（判定为**启动失败**）时 MUST 累计连续失败次数，连续失败达 3 次时 MUST 停止自动拉起 daemon，写入熔断标记并在 `.fenix/logs/supervisor.log` 落 critical 记录、经既有告警通道产出 critical 告警（描述 MUST 含「daemon 连续启动失败，已停止自动拉起」与人工处置指引）。daemon 存活超过 60 秒时 MUST 重置连续失败计数。

#### Scenario: 连续启动失败触发熔断

- **WHEN** daemon 连续 3 次在启动后 60 秒内退出（如自动重启引入了无法启动的新代码）
- **THEN** supervisor 停止拉起 daemon，写入熔断标记，落 critical 告警，不进入无限重启循环

#### Scenario: 存活足够久则重置失败计数

- **WHEN** daemon 启动后稳定运行超过 60 秒后因故退出
- **THEN** 连续失败计数重置为 0，下一次启动失败从 1 开始计数

#### Scenario: 熔断为人工可恢复

- **WHEN** 用户修复代码并清除熔断标记（或重启 supervisor 进程）
- **THEN** supervisor 恢复自动拉起 daemon，熔断前的失败计数不再影响新进程

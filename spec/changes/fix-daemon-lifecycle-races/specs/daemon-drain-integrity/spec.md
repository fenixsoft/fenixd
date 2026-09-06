# daemon-drain-integrity

## ADDED Requirements

### Requirement: 启动时终态补写扫描

daemon 启动时（AgentRunner 初始化后、任何 agent 派发前），SHALL 扫描 `.fenix/runs/*.jsonl`，对尾部不含终态事件（`result` / `interrupted` / `error` / `cancelled`，判定口径对齐 `runner.py:2595` `_run_was_interrupted`）的 run 文件追加 `{"type": "interrupted", "reason": "startup terminal-state sweep"}` 终态事件。补写 MUST 不依赖遗留 claude 进程的存活状态（run 文件由 daemon 侧转写，孤儿进程不会产生新事件）。daemon 正常运行期间不得重复执行该扫描。

#### Scenario: SIGKILL 遗留 run 被补写终态

- **WHEN** daemon 在途 run 被 supervisor SIGKILL（run 文件尾部为中途 transcript 事件、无终态），随后新 daemon 启动
- **THEN** 启动扫描对该 run 文件追加 interrupted 终态事件，聚合统计不再出现「在跑/无终态」

#### Scenario: 孤儿进程存活不阻塞补写

- **WHEN** daemon 被强杀后遗留的孤儿 claude 进程仍在运行，新 daemon 启动执行扫描
- **THEN** 对应 run 文件仍被补写 interrupted 终态（补写判定不检查进程存活）

#### Scenario: 正常运行的 run 不受影响

- **WHEN** daemon 正常运行期间派发新 run 并自然完成
- **THEN** 该 run 文件仅有 result 终态、无 sweep 补写事件（sweep 只在启动时执行一次）

### Requirement: supervisor SIGKILL 等待窗口自报

supervisor 进程启动时 SHALL 原子覆写 `.fenix/supervisor_runtime.json`，内容含 `sigkill_wait`（= `shutdown_drain_seconds + 120`，drain≤0 时为 60）与 `started_at`。

#### Scenario: supervisor 启动上报等待窗口

- **WHEN** supervisor 进程启动（首次或重启后）
- **THEN** `.fenix/supervisor_runtime.json` 存在且 `sigkill_wait` 与当前配置计算值一致

### Requirement: drain 窗口一致性自检

daemon 启动时若 `admin.shutdown_drain_seconds > 0`，SHALL 读取 `.fenix/supervisor_runtime.json`：文件缺失、或 `sigkill_wait < shutdown_drain_seconds + 120`、或 `started_at` 与 daemon 启动时间漂移超阈值时，打 WARNING 日志并写项目日志，提示「排水可能被截断，建议重启 supervisor」。

#### Scenario: 旧代码 supervisor 被检出

- **WHEN** supervisor 为未写 runtime 文件的旧代码进程，daemon 以 drain>0 配置启动
- **THEN** daemon 打 WARNING 告警（文件缺失分支），提示重启 supervisor

#### Scenario: 一致配置静默通过

- **WHEN** supervisor runtime 文件在册且 `sigkill_wait >= drain + 120`
- **THEN** daemon 启动不打一致性告警

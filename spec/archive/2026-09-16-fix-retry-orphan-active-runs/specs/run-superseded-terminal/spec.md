# spec: run-superseded-terminal

## ADDED Requirements

### Requirement: 原地重试弃置产物必须落终态（写侧）

runner 原地退避重试的两个通道（provider 瞬断 `runner.py:2168-2197`、artifact-gate `runner.py:2044-2071`）在写 `transient_retry` 事件、且后续将以新 `sub_run_id` 重开产物文件（`transient_retries` 递增 → `runner.py:1922-1923` 换新）或退出重试子循环时，必须先向当前产物文件补写一条 `type: "superseded"` 终态事件，再进入退避 sleep。补写后该文件末行恒为终态，恢复「终态后置」不变量。

#### Scenario: 原地重试换新文件前旧文件末行为 superseded

- **WHEN** 某 attempt 因 provider 瞬断（或 artifact-gate 失败）判定重试，写出 `transient_retry` 事件并完成退避 sleep
- **THEN** 旧产物文件（`<attempt_run_id>[-rN].jsonl`）末行为 `type: "superseded"` 事件（含 spec、provider、timestamp 字段）
- **AND** 重试 attempt 写入新文件 `<attempt_run_id>-r<N+1>.jsonl`，旧文件不再被追加

#### Scenario: daemon 在退避窗口内死亡时 interrupted 补写仍生效

- **WHEN** 补写 `superseded` 后、新 attempt 首事件落盘前 daemon 停机
- **THEN** 停机/启动清扫向该文件追加 `interrupted`（位于 superseded 之后，仍满足末行终态）

### Requirement: 读侧识别 superseded 终态

`core/dashboard/data.py` 的 `_RUN_TERMINAL_STATUS_MAP` 增 `superseded → superseded`；`classify_run` 对末行 `superseded` 判终态，不再落入 `running` 兜底。

#### Scenario: superseded 尾行判终态

- **WHEN** 产物文件末行为 `{"type": "superseded"}`
- **THEN** `classify_run` 返回 `"superseded"`（非 running）

### Requirement: 读侧 mtime 陈旧兜底（stale）

`get_runs` 判定中：产物末行非终态（`running`/`empty`）且文件 mtime 距今超过 `_RUN_STALE_SECONDS`（模块常量 1800 秒）→ 状态改判 `stale`。mtime 阈值内的非终态文件保持 `running`（真在退避/执行）。`stale` 为读侧专属状态枚举（不对应任何事件类型），不写入任何产物文件。

#### Scenario: 陈旧非终态文件判 stale 且不计入活跃

- **WHEN** 产物文件末行为 `transient_retry`（或普通对话行），mtime 停更 40 小时
- **THEN** `get_runs` 返回该 run `status: "stale"`
- **AND** `project_summary` 的 `active_runs` 不计入它（active 统计只认 `running`/`empty`）

#### Scenario: 退避窗口内的 transient_retry 尾行仍算活跃

- **WHEN** 产物文件末行为 `transient_retry`、mtime 距今 2 分钟（退避序列 30/60/120s 之内）
- **THEN** `get_runs` 返回 `status: "running"`，`project_summary` 计入 `active_runs`

#### Scenario: 存量尸体全量消化

- **WHEN** 对含 21 个 mtime 停更 ≥11 小时的 `transient_retry` 尾行文件的真实 `.fenix/runs/` 目录执行 `get_runs`
- **THEN** 全部判 `stale`，活跃计数回归真实值（在飞 run 数，无尸体）

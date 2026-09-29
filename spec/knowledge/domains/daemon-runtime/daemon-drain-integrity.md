<!-- knowledge: capability=daemon-drain-integrity rev=1 sources=spec/archive/2026-09-12-fix-daemon-lifecycle-races -->

# daemon 启动终态补写与排水一致性

daemon 在启动窗口内自证运行记录完整、并核对自身与 supervisor 的排水配置一致，防止 SIGKILL 遗留的 run 永久悬挂「在跑」、排水被静默截断。

## 现行规则

- daemon 启动时（AgentRunner 初始化后、任何 agent 派发前）扫描 `.fenix/runs/*.jsonl`：尾部不含终态事件（`result`/`interrupted`/`error`/`cancelled`）的 run 文件补写 `{"type": "interrupted", "reason": "startup terminal-state sweep"}` 终态事件。
- 补写判定不依赖遗留 claude 进程的存活状态（run 文件由 daemon 侧转写，孤儿进程不会产生新事件）；该扫描仅在启动时执行一次，正常运行期间不重复。
- supervisor 进程启动时原子覆写 `.fenix/supervisor_runtime.json`，自报 `sigkill_wait`（= `admin.shutdown_drain_seconds + 120`；drain≤0 时为 60）与 `started_at`（该文件的完整键集见 [supervisor-hosting](supervisor-hosting.md)）。
- daemon 以 drain>0 启动时执行排水一致性自检：`supervisor_runtime.json` 缺失、`sigkill_wait < shutdown_drain_seconds + 120`、或 `started_at` 与 daemon 启动时间漂移超阈值时，打 WARNING 日志并写项目日志，提示「排水可能被截断，建议重启 supervisor」；配置一致则静默通过，不打告警。

## 溯源

- [2026-09-12 fix-daemon-lifecycle-races](spec/archive/2026-09-12-fix-daemon-lifecycle-races/) — 新增启动时终态补写扫描、supervisor SIGKILL 等待窗口自报与 drain 窗口一致性自检

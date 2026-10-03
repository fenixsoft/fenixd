# daemon 启动终态补写与排水一致性

<!-- knowledge: capability=daemon-drain-integrity rev=2
     sources=spec/archive/2026-09-12-fix-daemon-lifecycle-races,spec/archive/2026-10-04-evo-supervisor-drift-log-dedup -->

daemon 在启动窗口内自证运行记录完整、并核对自身与 supervisor 的排水配置一致，防止 SIGKILL 遗留的 run 永久悬挂「在跑」、排水被静默截断；自检告警落项目日志经窗口去重防重启刷屏。

## 规则

- daemon 启动时（AgentRunner 初始化后、任何 agent 派发前）扫描 `.fenix/runs/*.jsonl`：尾部不含终态事件（`result`/`interrupted`/`error`/`cancelled`）的 run 文件补写 `{"type": "interrupted", "reason": "startup terminal-state sweep"}` 终态事件。
- 补写判定不依赖遗留 claude 进程的存活状态（run 文件由 daemon 侧转写，孤儿进程不会产生新事件）；该扫描仅在启动时执行一次，正常运行期间不重复。
- supervisor 进程启动时原子覆写 `.fenix/supervisor_runtime.json`，自报 `sigkill_wait`（= `admin.shutdown_drain_seconds + 120`；drain≤0 时为 60）与 `started_at`（该文件的完整键集见 [supervisor-hosting](supervisor-hosting.md)）。
- daemon 以 drain>0 启动时执行排水一致性自检：`supervisor_runtime.json` 缺失、`sigkill_wait < shutdown_drain_seconds + 120`、或 `started_at` 与 daemon 启动时间漂移超阈值（SUPERVISOR_RUNTIME_DRIFT_SECONDS，缺省 24 小时）时产出 supervisor 异常族警告，提示「排水可能被截断，建议重启 supervisor」；配置一致则静默通过，不打告警。
- 自检警告经框架日志逐条落 WARNING，每次启动照常落、不受去重影响；向 PROJECT_LOG 追加则先做窗口去重：以 AdminStore 持久告警存储为去重状态源，`SUPERVISOR_LOG_DEDUP_MINUTES`（默认 60 分钟）窗口内已存在同键（`signal_type=supervisor_runtime_drift`）记录时跳过本次追加。
- 去重判定为族级粗粒度、按 signal_type 键判定，不逐字匹配告警文案（文案含运行时数值与时间戳，跨重启漂移）；窗口命中时本次检查产生的全部 supervisor 异常族警告一并跳过 PROJECT_LOG 追加，窗口内不同子类异常（如 sigkill_wait 余量不足与漂移并存）不单独成条。
- 首次成条时同步写入一条去重标记记录（`kind=escalation`、`signal_type=supervisor_runtime_drift`、`spec=None`、`severity=warning`，写入即自动 mark_handled、不进人工告警横幅/待处理队列，仅作历史记录保留）；`spec` 必须为 None——`latest_signal` 的 spec=None 查询只匹配 spec=None 记录，标记带 spec 值会使窗口判定永不命中、去重静默失效。标记持久于 admin_alerts.json，去重状态因此跨 daemon 重启存活；超窗后新异常周期照常成条并刷新窗口标记。
- 去重命中不静默：写一条框架日志（info 级）说明窗口去重命中、命中键与被跳过的警告条数。
- admin_store 不可用（None）或去重读写抛异常时降级为照常追加 PROJECT_LOG（等价现状行为），并记一条框架警告日志说明去重状态不可用；去重机制本身不得造成告警丢失或启动失败。
- 窗口去重仅覆盖排水一致性自检的 PROJECT_LOG 追加路径；supervisor_missing 路径沿用既有 unhandled_for 去重、stale_code 通道沿用既有窗口去重，互不变更。告警去重属产生告警的业务检查点语义，不下沉进共享日志通道 `_append_project_log`（见 [ADR-222](../../adr/ADR-222-project-log-alert-dedup-at-business-check-site.md)）。

## 溯源

- 2026-09-12 fix-daemon-lifecycle-races（spec/archive/2026-09-12-fix-daemon-lifecycle-races） — 新增启动时终态补写扫描、supervisor SIGKILL 等待窗口自报与 drain 窗口一致性自检
- 2026-10-04 evo-supervisor-drift-log-dedup（spec/archive/2026-10-04-evo-supervisor-drift-log-dedup） — 排水一致性自检告警的 PROJECT_LOG 追加新增 60 分钟跨重启窗口去重（AdminStore 状态承载、族级键判定、命中留痕、状态源不可用降级照常追加）

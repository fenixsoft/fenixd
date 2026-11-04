# 守护进程平台
> 最后更新：2026-11-04 17:46 UTC+8

守护进程平台域：daemon 进程生命周期、单例与托管链、启动序列与排水语义、结构化日志单事件读写治理、宿主环境已知脆弱面登记。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [daemon-singleton](daemon-singleton.md) | daemon 单例保证 | 2026-10-03 04:59 |
| [daemon-health](daemon-health.md) | daemon 健康监控 | 2026-10-03 04:59 |
| [daemon-watcher-startup](daemon-watcher-startup.md) | Agent 派发异步化与 watcher 启动 | 2026-10-03 04:59 |
| [daemon-drain-integrity](daemon-drain-integrity.md) | 启动终态补写与排水一致性自检（告警窗口去重、恢复重派误杀签名） | 2026-11-04 17:46 |
| [daemon-error-escalation](daemon-error-escalation.md) | daemon 错误升级上报（指纹归一化保守集+SPEC 名剥离） | 2026-10-31 16:23 |
| [crossday-recurrence-detection](crossday-recurrence-detection.md) | daemon 错误跨日同刻复发检测（只读聚合观测） | 2026-10-11 02:02 |
| [graceful-restart-drain](graceful-restart-drain.md) | 优雅重启排水窗口（重启前置双条件停驻判据、冻结不加速重启） | 2026-11-04 16:30 |
| [supervisor-hosting](supervisor-hosting.md) | supervisor 托管链（托管态判定与启停语义、宿主级事件暴露面、tmux 连坐机制与运维纪律、整链人工重建、supervisor_fused 解熔断 compileall 核验） | 2026-11-04 16:30 |
| [host-env-hazards](host-env-hazards.md) | 宿主环境已知脆弱面（网关 DNS 失效 drop-in 绕过待 revert、dns_probe_failed 归因判读） | 2026-11-04 16:11 |
| [state-watch-event-bus](state-watch-event-bus.md) | STATE.md 变更监视与事件派发总线 | 2026-09-27 17:23 |
| [structured-log-rotation](structured-log-rotation.md) | JSON 结构化日志与跨进程安全轮转 | 2026-09-27 17:23 |
| [framework-install](framework-install.md) | 框架安装（依赖检查与软链装配） | 2026-09-27 17:23 |
| [cli-process-report](cli-process-report.md) | SPEC 进度 CLI 报告（/fenix-process 数据源） | 2026-09-27 17:23 |
| [cli-status-panel](cli-status-panel.md) | 框架状态面板报告（/fenix-status 数据源） | 2026-09-27 17:23 |
| [daemon-log-event-governance](daemon-log-event-governance.md) | daemon 日志单事件读写治理（写侧序列化 256KB 封顶 truncated 留痕、读侧锚定窗口跳过超长行不整读入内存） | 2026-10-30 23:11 |

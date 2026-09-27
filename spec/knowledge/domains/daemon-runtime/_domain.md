# 守护进程平台

守护进程平台域：daemon 进程生命周期、单例与托管链、启动序列与排水语义。

## 能力页

- [daemon-singleton](daemon-singleton.md) — daemon 单例保证
- [daemon-health](daemon-health.md) — daemon 健康监控
- [daemon-watcher-startup](daemon-watcher-startup.md) — Agent 派发异步化与 watcher 启动
- [daemon-drain-integrity](daemon-drain-integrity.md) — 排水期完整性保证
- [daemon-error-escalation](daemon-error-escalation.md) — daemon 错误升级上报
- [graceful-restart-drain](graceful-restart-drain.md) — 优雅重启排水窗口
- [supervisor-hosting](supervisor-hosting.md) — supervisor 托管链
- [state-watch-event-bus](state-watch-event-bus.md) — STATE.md 变更监视与事件派发总线
- [structured-log-rotation](structured-log-rotation.md) — JSON 结构化日志与跨进程安全轮转
- [framework-install](framework-install.md) — 框架安装（依赖检查与软链装配）
- [cli-process-report](cli-process-report.md) — SPEC 进度 CLI 报告（/fenix-process 数据源）
- [cli-status-panel](cli-status-panel.md) — 框架状态面板报告（/fenix-status 数据源）

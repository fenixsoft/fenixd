# 守护进程平台
> 最后更新：2026-11-27 17:28 UTC+8

守护进程平台域：daemon 进程生命周期、单例与托管链（systemd unit 承载、on-failure 重启策略与 supervisor 退出码协议、env 捕获 PATH 卫生）、启动序列与排水语义、计划内重启排水窗与在飞 run 保护（checkpoint 旗标批边界响应、writeoff 锚即时续审）、结构化日志单事件读写治理、宿主环境已知脆弱面登记。Windows 原生承载链（PowerShell 安装链、安装链可观测性与制品骨架完整性、dockur 过机验收通道与双平台 CI）也在此域。框架与插件的自动更新闭环（版本发现、周期检查、一键换装与回滚、源码形态降级）也在此域。

## 能力页

| 能力页 | 简介 | 更新时间 |
| --- | --- | --- |
| [daemon-singleton](daemon-singleton.md) | daemon 单例保证 | 2026-10-03 04:59 |
| [daemon-health](daemon-health.md) | daemon 健康监控 | 2026-11-05 04:11 |
| [daemon-watcher-startup](daemon-watcher-startup.md) | Agent 派发异步化与 watcher 启动 | 2026-10-03 04:59 |
| [daemon-drain-integrity](daemon-drain-integrity.md) | 启动终态补写与排水一致性自检（告警窗口去重、漂移分支经 pid 存活门控分级、恢复重派误杀签名） | 2026-11-16 22:30 |
| [daemon-error-escalation](daemon-error-escalation.md) | daemon 错误升级上报（指纹归一化保守集+SPEC 名剥离） | 2026-10-31 16:23 |
| [crossday-recurrence-detection](crossday-recurrence-detection.md) | daemon 错误跨日同刻复发检测（只读聚合观测） | 2026-10-11 02:02 |
| [graceful-restart-drain](graceful-restart-drain.md) | 优雅重启排水窗口（重启前置双条件停驻判据、冻结不加速重启） | 2026-11-17 00:24 |
| [daemon-lifecycle](daemon-lifecycle.md) | 计划内排水窗与在飞 run 保护（有效窗推导与夹短告警、planned 专用 SIGKILL 回退 310、批边界旗标自检退出落锚、writeoff 锚周期扫描即时续审与 writeoff_resume 注记） | 2026-11-17 00:24 |
| [systemd-hosting](systemd-hosting.md) | systemd 承载的托管链（unit 形态与幂等安装、Restart=on-failure 与 supervisor 退出码协议、EnvironmentFile 环境承载、env 捕获源按执行会话形态分源与 denylist、stop 双轨、dashboard unit 接管豁免、restart-dashboard 迁移、一次性搬迁编排） | 2026-11-27 17:28 |
| [systemd-env-path-hygiene](systemd-env-path-hygiene.md) | systemd env 捕获 PATH 卫生（捕获稿基线并集补齐留痕、unit 模板保底 Environment=PATH、迁移摘要卫生结论） | 2026-11-08 21:21 |
| [supervisor-hosting](supervisor-hosting.md) | supervisor 托管链（托管态判定与 systemctl 双轨启停语义、信号消费校验、runtime 漂移告警 pid 存活门控分级、整链人工重建、supervisor_fused 解熔断 compileall 核验） | 2026-11-16 22:30 |
| [host-env-hazards](host-env-hazards.md) | 宿主环境已知脆弱面（网关 DNS 失效 drop-in 绕过待 revert、dns_probe_failed 归因判读、spawn 层失败三查判读、宿主 /dev/null 设备损坏判读与重建配方、dashboard unit 缺席 tmux 兜底常驻待收口） | 2026-11-13 01:30 |
| [windows-native-support](windows-native-support.md) | Windows 原生进程全功能运行交付面：安装链 PowerShell 化与依赖独立清单、安装链可观测性（首装零噪音/输出编码安全）、运行时日志卫生、skill 双平台命令口径、制品与骨架完整性 fail-fast（含 spec CLI schema 前置）、harness CLI 可执行解析单源、确定性 spawn 失败一跳终态（归因三型）、服务环境注入与自检（AppEnvironmentExtra/env_defect、USERPROFILE 缺省注入与漂移判读、安装手册一步形态）、优雅终止三层协议、dockur 过机验收通道（G1 全功能对等 25 条、win-vm 标准姿势执行）与环境止损纪律、过机通道实测纪律、双平台 CI、过机复验铁则 | 2026-11-16 21:09 |
| [state-watch-event-bus](state-watch-event-bus.md) | STATE.md 变更监视与事件派发总线（固定 2 秒间隔轮询 + checksum，无 inotify） | 2026-11-11 13:59 |
| [structured-log-rotation](structured-log-rotation.md) | JSON 结构化日志与跨进程安全轮转 | 2026-09-27 17:23 |
| [framework-install](framework-install.md) | 框架安装（依赖检查与软链装配） | 2026-09-27 17:23 |
| [auto-update](auto-update.md) | 框架与 dsh-plugins 自动更新闭环（VERSION 单源与形态判定、releases/latest 双腿查询、daemon 周期检查与框架级共享状态、运维页更新卡与三 API、分离编排三段式换装、单代回滚与幂等恢复、插件 remove+add 重注册、`update:` 配置段、审计留痕） | 2026-11-25 18:25 |
| [cli-process-report](cli-process-report.md) | SPEC 进度 CLI 报告（/fenix-process 数据源） | 2026-09-27 17:23 |
| [cli-status-panel](cli-status-panel.md) | 框架状态面板报告（/fenix-status 数据源） | 2026-09-27 17:23 |
| [daemon-log-event-governance](daemon-log-event-governance.md) | daemon 日志单事件读写治理（写侧序列化 256KB 封顶 truncated 留痕、读侧锚定窗口跳过超长行不整读入内存） | 2026-10-30 23:11 |

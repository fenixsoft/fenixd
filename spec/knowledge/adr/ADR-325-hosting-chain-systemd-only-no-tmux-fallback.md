# ADR-325：托管链承载单源 systemd，tmux 承载退役不设回退

date: 2026-11-04
status: accepted

## Context

supervisor→daemon→dashboard 托管链此前只承载于 tmux 会话，无任何进程外监督者：宿主机级全用户态 SIGKILL 事件（内核与 systemd 存活）后整链无人拉起、停机 7.75 小时，supervisor 看门狗自身也是链内进程（「看门狗没有看门狗」）；tmux server 单例死亡亦会连坐整链。进程内加固（SIGHUP handler、setsid）防不了宿主机级事件，只有 systemd 能在「全部进程死亡」后拉回托管链——有 unit 的 `dsh-web.service` 在同一事件中自动恢复，形成对照。

## Decision

托管链承载层单源 systemd：每项目一条 `fenixd-<项目名>.service`（ExecStart=supervisor，daemon 保持为其子进程，systemd 的监督对象是 supervisor）+ 框架主树 `fenix-dashboard.service`，均 `WantedBy=multi-user.target` 开机自启。start/stop 运维接口全部迁 systemctl 语义（stop 按 unit 接管状态双轨，managed-but-no-unit 态保留直接信号链）；`systemctl` 不可用或无权限时拒绝启动并报可读错误，不静默降级回 tmux；tmux 承载路径与会话名体系退役，不做非 systemd 环境适配。存量部署经一次性搬迁脚本切换（写 unit 不启用 → 旧语义专用路径拆旧链 → enable --now，保证无双托管窗口），真实切换为人工步骤。

## Consequences

- 宿主机级事件与单进程崩溃的恢复不再依赖人工：supervisor、daemon、dashboard 全部由 systemd 自动拉回，开机自启成立。
- 非 systemd 宿主不被支持：systemctl 可用性成为部署硬性前置（依赖检查与启动错误路径均按此报错）。
- tmux 不再出现在任何托管配方中；诊断看现场改走 `journalctl` + 既有日志文件，日志文件布局不变。
- stopped 项目不预装 unit，获得承载发生在首次启动；「managed 但无 unit」态长期滞留需依赖 supervisor_missing 告警与 install-hosting 幂等补装兜底。
- stop 双轨长期并存增加维护面：managed-but-no-unit 是迁移期/异常态，主轨为 systemctl，后续可观测后收窄。

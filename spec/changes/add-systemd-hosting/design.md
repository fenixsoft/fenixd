## Context

2026-11-04 宿主机全用户态 SIGKILL 事件暴露托管链单点：supervisor→daemon→dashboard 只住在 tmux、无 systemd unit，事件后停机 7.75h（有 unit 的 `dsh-web.service` 自动恢复）。完整设计见 `docs/superpowers/specs/2026-11-04-systemd-hosting-design.md`（含 builder check 8 条定案），本文件承载实现级决策。

现行锚点：`core/fenix_session.py:454 start_daemon` / `:690 stop_daemon`（tmux 承载）；`bin/fenixd_supervisor.py`（SIGTERM 转发收尾、stop 旗标、熔断、单实例锁）；`core/dashboard/server.py`（`_bind_parent_lifecycle` PPID==1+DETACH 门、`_parent_is_tmux_server` 接管豁免、claude-watchdog）；`core/hook_engine.py` 内置 `pushed → restart-dashboard`（tmux has-session/respawn-window）；部署事实：claude CLI 在 `/root/.local/bin`、代理四件套指向 clash `127.0.0.1:20122`、`ANTHROPIC_BASE_URL=bigmodel` 网关。

## Goals / Non-Goals

Goals：宿主机级事件/进程崩溃后全链自动恢复；真机重启自动上线；tmux 从托管链退役（不留回退）；既有托管语义（restart_request/排水/script_hash/三态判定/告警/熔断）零变化。

Non-Goals：不迁移 stopped 项目；不动 dsh-web.service；不做非 systemd 环境适配；不改日志文件布局（读侧零改动）。

## Decisions

1. **`Restart=on-failure` + 退出码协议（0/75），不用 `Restart=always`**——always 会结构性架空熔断（新 pid 清熔断标记→再拉→再熔断循环+每轮 critical 告警风暴）。0=停机收尾/stop 旗标，75=熔断/放弃看护；恢复均人工。替代方案（always+StartLimit 兜底）被否：熔断语义实质改变。
2. **EnvironmentFile（0600）+ 机械捕获脚本 + 会话身份 denylist**，而非手工维护 env 清单或裸写 unit。denylist 用前缀族（CLAUDE_PID/CLAUDECODE/CLAUDE_CODE_*/AI_AGENT/IS_SANDBOX/GIT_ASKPASS）；候选稿供人工审核后启用；切换冒烟=最小 agent spawn。替代方案（unit 内 `Environment=`）被否：unit 全局可读、密钥不可入。
3. **dashboard unit 必设 `FENIX_DASHBOARD_DETACH=1`**——server.py 在 PPID==1 且缺该变量时 exit(1)，systemd 主进程 PPID 恒 1，不设则无限崩溃循环。
4. **stop 双轨**：unit 已装走 `systemctl stop --no-block` + 既有 ≤30s 轮询 + 超时补杀（同步 `systemctl stop` 最坏 2100s 会挂死 HTTP 线程，破坏现行有界契约）；managed-but-no-unit 态保留既有直接信号链（`systemctl stop` 对未启动 unit 是 no-op，不能谎报成功）。
5. **搬迁脚本独立于迁移后启停函数**，顺序=写 unit 不启用→旧语义专用路径拆旧链→enable --now。「先启用再拆」被否：撞单实例锁与 8787 接管守卫，进崩溃循环，且迁移后 stop 拆不动旧链。
6. **unit 承载实例（PPID=1）纳入不可接管豁免**，与 tmux 承载豁免并列——防手工实例与 systemd 拉回互相接管的闪断循环。
7. **hook_engine restart-dashboard 迁 systemctl restart**，unit 缺席维持静默 skip（与 tmux 无会话对齐）；legacy target 键容忍不消费。

## Risks / Trade-offs

- [env 候选集漏掉 load-bearing 键 → 迁移后 agent run 失败] → 捕获脚本以在跑进程 environ 为源（非白名单凭记忆）；切换冒烟最小 spawn + 网关健康探测；失败即回滚（disable unit + 旧配方重启）。
- [退出码 0 的意外崩溃路径不被拉回（如 bug 导致干净退出）] → 与现状等价（今天 supervisor 干净退出同样无人拉回），非回归；StartLimit+on-failure 已覆盖 crash 主面。
- [「managed 但无 unit」态长期滞留（unit 被卸载后无人发现）] → supervisor_missing 告警既有判定基于 /proc 不受影响；install-hosting 端点幂等可补装 unit。
- [双轨 stop 长期并存增加维护面] → managed-but-no-unit 是迁移期/异常态，主轨为 systemctl；后续可观测后收窄。

## Migration Plan

实现合并不自动切换（在跑 daemon 是实现链宿主）。交付后人工执行：跑 env 捕获脚本 → 审核候选稿 → `bin/migrate_to_systemd.py`（先 dry-run 后真切换）→ 验收四件套。回滚：`systemctl disable --now` 两条 unit → 旧配方（tmux）重启托管链。人工步骤记入 `.fenix/todo.md`。

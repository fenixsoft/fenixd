<!-- knowledge: capability=systemd-hosting rev=1
     sources=spec/changes/add-systemd-hosting -->

# systemd 承载的托管链

systemd unit 是托管链的承载与进程外监督层：supervisor、daemon、dashboard 全部由 unit 拉起，异常死亡后被 systemd 自动拉回，宿主机级事件（全用户态进程死亡）与单进程崩溃都不再依赖人工恢复。systemd 是唯一能在全部进程死亡后拉回托管链的进程外监督者；tmux 不在托管链中。

## 规则

- unit 形态与安装：每项目一条静态 unit `fenixd-<项目名>.service`（项目名做文件名安全化，`WorkingDirectory=<项目根>`、`ExecStart=python3 .fenix/bin/fenixd_supervisor.py --project-root <项目根>`）；框架主树一条 `fenix-dashboard.service`（`ExecStart=python3 .fenix/bin/fenix_dashboard.py --serve`）。systemd 的监督对象是 supervisor，daemon 保持为 supervisor 子进程。两类 unit 均 `WantedBy=multi-user.target`（宿主机重启后开机自启）、`Restart=on-failure`、`RestartSec=5s`、`TimeoutStopSec=2100` 与 `StartLimitIntervalSec=120s`/`StartLimitBurst=5`（crash-loop 最后兜底）；项目 unit 另有 `KillMode=mixed`（SIGTERM 只发主进程，由 supervisor 自行转发收尾 daemon）与 `SuccessExitStatus=75`。安装即 `systemctl enable --now`，操作幂等：unit 已存在且服务活跃时重复安装不重建、不重启（返回 already）。`systemctl` 不可用或无权限时打印含「需要 systemd」指引的可读错误并拒绝启动，不静默降级为 tmux。stopped 项目不预装 unit，获得承载发生在首次启动时；非框架 unit（如 `dsh-web.service`）不在托管范围内。

- 重启策略与 supervisor 退出码协议：`Restart=on-failure` 下一切异常退出形态（SIGKILL、异常非零码）都被 systemd 拉回，含 dashboard 进程单独崩溃（:8787 自动恢复）。supervisor 四条有意退出路径的退出码是对外协议：停机信号收尾与 `.fenix/stop` 旗标在场退出 → 0；熔断退出（supervisor_fused）与兜底收尸/收编超限放弃看护 → 75。0 与 75 经 `SuccessExitStatus` 声明为成功、不被拉回——熔断后 unit inactive（非 failed）、告警仅一条、恢复一律人工，熔断「停止自动重试、恢复交人工」的语义不因 systemd 拉回而架空。dashboard 无熔断/放弃看护语义，不适用退出码协议，SIGTERM 干净收尾退出 0 在 on-failure 下本就不拉回。不采用 `Restart=always`：always 会在熔断退出后拉起新 pid 清掉熔断标记，形成「再拉→再熔断」循环加每轮 critical 告警风暴。后续新增 supervisor 有意退出路径必须归入 0 或 75 并同步 unit 模板。

- unit 运行环境承载：经 `EnvironmentFile`（0600，root 属主）承载，密钥不裸写进 unit 文件（unit 全局可读）；unit 以 `-` 前缀引用 EnvironmentFile，候选稿未提升时 unit 仍可启动。env 来源是捕获脚本从在跑 daemon/dashboard 的 `/proc/<pid>/environ` 机械捕获候选键集（以在跑进程实况为源，不靠白名单凭记忆），再套会话身份 denylist：剥离 `CLAUDE_PID`、`CLAUDECODE`、`CLAUDE_CODE_*` 前缀族、`AI_AGENT`、`IS_SANDBOX`、`GIT_ASKPASS` 等会话专属键；保留 `PATH`（须含 `/root/.local/bin`）、`HOME`、`LANG`、代理四件套（`HTTP_PROXY`/`HTTPS_PROXY`/`http_proxy`/`https_proxy` 值原样）、`ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_DEFAULT_*`、`API_TIMEOUT_MS`。候选稿经人工审核后提升为正式 EnvironmentFile。dashboard unit 必设 `FENIX_DASHBOARD_DETACH=1`：serve 在 PPID==1 且该变量缺位时拒绝启动 exit(1)（systemd unit 主进程 PPID 恒为 1，缺位即无限崩溃循环）；unit 环境无 `CLAUDE_PID`，claude-watchdog 不绑定，长驻豁免成立。

- 托管停止的 systemctl 双轨（`stop_daemon` 全序见 [supervisor 托管链](supervisor-hosting.md)）：unit 已安装走 systemd 轨——写 `.fenix/stop` 后 `systemctl stop --no-block` 触发 supervisor 既有 SIGTERM 转发收尾，配既有 ≤30 秒轮询确认与超时补杀；不同步等待 `systemctl stop`（其最坏等待为排水上界量级，会挂死调用线程）。managed-but-no-unit 态（迁移期、人工直启、unit 被手工卸载）走既有直接信号链，不因 `systemctl stop` 对未启动 unit 是 no-op 而谎报成功。

- dashboard unit 承载实例的接管豁免：「父进程为 PID 1 的常驻实例」不可被接管——启动方（手工 `--serve`、agent 自测实例）MUST NOT 对其发送任何信号，打印含占用者 PID 与「`systemctl restart fenix-dashboard` 重启生产实例或 `--port` 换端口」指引的可读错误后非 0 退出；判定实现 `_parent_is_pid1` 与 tmux 承载判据并列、解析纪律同源。防「手工实例接管 → systemd 拉回 → 反向接管」的生产实例闪断循环。dashboard 日常重启走 `systemctl restart fenix-dashboard`。

- restart-dashboard 内置动作：hook_engine 内置默认条目 `pushed → restart-dashboard` 的执行侧为 `systemctl restart fenix-dashboard`，以端口恢复可服务定成败。`fenix-dashboard` unit 未安装时维持静默 skip（审计记 skipped，不报错、不产生失败告警）。用户 config 中该动作的 legacy `target` 键（tmux 会话名）容忍存在但不消费。

- 一次性搬迁编排：`bin/migrate_to_systemd.py`（支持 `--dry-run`，dry-run 零副作用）按固定顺序编排——① 写 unit 文件与 EnvironmentFile 候选稿（不 enable）→ ② 经旧语义专用路径拆旧 tmux 承载链（迁移后的 start/stop 对 unit 不拥有的旧链无能为力，不复用迁移后启停函数；旧 dashboard 实例直接 kill pid 并等待端口释放）→ ③ `systemctl enable --now` 两条 unit → ④ 验收（进程在位、端口监听、退出码语义、自愈/env 冒烟）。顺序不可倒置：先 enable 再拆会撞单实例锁与 :8787 接管守卫进入崩溃循环，且迁移后 stop 拆不动旧链；全程任意时刻至多一条托管链、一个 :8787 实例（无双托管窗口）。真实切换必须人工执行（拆的是在跑 daemon 本尊）：Agent 交付脚本落位与 dry-run 预演，人工审核 env 候选稿并执行真切换；env 缺键致 run 失败即回滚（disable 两条 unit + 旧配方重启）。

- 运维接口与配方语义：启停、看现场、重启协议全部 systemctl/journalctl 语义（`/fenix-setup`、`/fenix-dashboard` SKILL.md 与 `docs/help/` 同此口径）；看现场 = `journalctl -u <unit>` 加既有 `.fenix/logs/` 日志文件，日志文件布局不受承载层影响（读侧零改动）。

## 溯源

- 2026-11-04 add-systemd-hosting（spec/changes/add-systemd-hosting） — 新建本能力：unit 形态与幂等安装（systemctl 不可用拒绝不降级 tmux）、`Restart=on-failure` + supervisor 退出码协议（0/75 不拉回、StartLimit 兜底）、EnvironmentFile（0600）+ 机械捕获 + 会话身份 denylist、dashboard DETACH 门与接管豁免、restart-dashboard 执行侧迁 systemctl、一次性搬迁编排（`bin/migrate_to_systemd.py`，真实切换人工）

## Why

2026-11-04 宿主机全用户态 SIGKILL 事件实证：有 systemd unit 的服务自动恢复，fenixd 托管链（supervisor→daemon→dashboard）只住在 tmux、无任何 unit，停机 7.75 小时。systemd 是唯一能在「全部进程死亡」后拉回的进程外监督者；进程内加固（SIGHUP handler/setsid）防不了宿主机级事件，且 supervisor 看门狗自身也是链内进程（「看门狗没有看门狗」）。

## What Changes

- 新增 systemd 承载层：每项目一条 `fenixd-<项目名>.service`（ExecStart=supervisor，daemon 保持为其子进程）+ `fenix-dashboard.service`；`Restart=on-failure` + supervisor 有意退出路径退出码协议（0=显式停止/停机收尾，75=熔断/放弃看护——不被拉回，防熔断被架空为告警风暴）；`WantedBy=multi-user.target` 开机自启。
- unit 运行环境经 `EnvironmentFile`（0600）承载：env 捕获脚本从在跑进程机械捕获并套会话身份 denylist（剥离 CLAUDE_PID/CLAUDE_* 等），保留 PATH（含 /root/.local/bin）/HOME/代理四件套/ANTHROPIC_* 网关键；dashboard unit 必设 `FENIX_DASHBOARD_DETACH=1`（PPID==1 无此变量拒绝启动）。
- **BREAKING**（承载层语义，对内运维接口）：`start_daemon`/`stop_daemon` 从 tmux 承载迁到 systemctl 语义——start 缺 unit 即生成安装并 `enable --now`；stop 双轨（unit 已装走 `systemctl stop --no-block`+既有 ≤30s 轮询+超时补杀；「managed 但无 unit」态保留既有直接信号链）；tmux 承载路径与会话名体系退役。
- supervisor 四条有意退出路径落实退出码协议；crash 路径退出码不变。
- dashboard unit 承载实例加不可接管豁免（PPID=1 常驻实例不可被手工 `--serve` 接管，防接管↔拉回循环闪断）。
- hook_engine 内置 `pushed → restart-dashboard` 动作执行侧迁 `systemctl restart`（tmux 退役后现实现会静默死亡）；unit 缺席维持静默 skip。
- 一次性搬迁：`bin/migrate_to_systemd.py`（写 unit 不启用 → 旧语义专用路径拆旧 tmux 链 → enable --now → 验收），支持 `--dry-run`；真切换为人工步骤（脚本落位+dry-run 为 Agent 任务）。
- `/fenix-setup`、`/fenix-dashboard` SKILL.md 配方改 systemctl 语义（看现场=journalctl+既有日志文件）。

## Capabilities

### New Capabilities
- `systemd-hosting`: systemd 承载的托管链——unit 形态与安装、重启策略与 supervisor 退出码协议、unit 运行环境承载（EnvironmentFile+denylist）、stop 双轨语义、dashboard unit 承载（DETACH/接管豁免）、restart-dashboard 动作迁移、一次性搬迁编排、自愈验收。

### Modified Capabilities
- `supervisor-hosting`（现行规则见 spec/knowledge/domains/daemon-runtime/supervisor-hosting.md，快照在 spec/archive/2026-09-18-fix-supervisor-hosting-chain/specs/supervisor-hosting/spec.md）：托管启动路径不再经项目 tmux session（改 unit 安装+enable --now，幂等 already 语义保持）；stop 兜底不再 tmux kill-session（改 systemctl stop 双轨）；熔断/放弃看护等有意退出获得退出码协议。

## Impact

- 代码：`core/fenix_session.py`（start/stop 迁移）、新 `core/systemd_hosting.py`（unit 模板/安装/env 捕获）、`bin/fenixd_supervisor.py`（退出码）、`core/dashboard/server.py`（接管豁免）、`core/hook_engine.py`（restart-dashboard）、新 `bin/migrate_to_systemd.py`。
- 运维接口：启停/看现场/重启协议全变 systemctl/journalctl 语义（skills 配方同步）；本机 fenixd 项目需一次性人工切换搬迁。
- 不影响：daemon/supervisor 业务语义（restart_request、排水、script_hash、hosting 三态判定、supervisor_missing 告警）、日志文件布局、dsh-web.service、stopped 项目（获得能力不迁移）。

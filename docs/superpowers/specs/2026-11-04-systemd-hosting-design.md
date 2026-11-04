# fenixd 托管链 systemd 化设计（systemd 彻底替代 tmux 承载层）

日期：2026-11-04（同日二稿：回填 builder check 8 条定案）
状态：已定稿（brainstorm 收敛，用户拍板三项决策 + builder check 全部定案），转 fenix-new 立项

## 背景与动机

2026-11-04 00:53 宿主机发生全用户态 SIGKILL 事件（内核/systemd[1] 存活）：有 systemd unit 的服务（如 `dsh-web.service`）在事件后自动恢复，而 fenixd 的 supervisor→daemon→dashboard 整条托管链只住在 tmux、无任何 unit，无人拉起，停机 7.75 小时至人工按配方恢复。

systemd 是唯一能在「全部进程死亡」后拉回的**进程外**监督者；进程内加固（SIGHUP handler、setsid）防不了全用户态 SIGKILL。此外 supervisor 看门狗自身也是链条内进程，「看门狗没有看门狗」的问题在宿主机级事件下必然暴露。

## 用户拍板的决策

1. **systemd 彻底替代 tmux 承载层**——不是兜底、不是并存，tmux 从托管链退役。
2. **开机自启**（enable）——机器真重启后框架自动恢复运转、照常派发。
3. **通用能力，不做项目级特殊处理**——所有 fenixd 项目一视同仁可装；本次实际落地 = fenixd（managed）+ dashboard 两个常驻服务，其余 4 个 stopped 项目只获得能力、不迁移。

## 目标

- 进程崩溃 / 宿主机级事件后，supervisor、daemon、dashboard 全部由 systemd 自动拉回。
- 机器真重启后 fenixd daemon 与 dashboard 自动上线（WantedBy=multi-user.target）。
- 托管链既有语义零变化：restart_request 消费、排水与 sigkill_wait 动态窗、script_hash 陈旧度凭据、hosting 三态判定、install-hosting 端点、supervisor_missing 告警、**熔断语义（supervisor_fused）**。
- 启停入口从 tmux 语义整体迁移到 systemctl 语义：`start_daemon`/`stop_daemon`/install-hosting、dashboard 重启协议（含 hook_engine 内置 `restart-dashboard` 动作）、`/fenix-setup` 与 `/fenix-dashboard` 配方。

## 非目标

- 不改 daemon/supervisor 业务语义（信号转发收尾、排水窗口、熔断判定、restart_request 协议全部保持；仅退出**码**按下文协议约定）。
- 不迁移 stopped 项目（没有进程要搬，下次启动自然走新路径）。
- 不动 `dsh-web.service`（已存在，不归 fenixd 管）。
- 不保留 tmux 承载回退、不做非 systemd 环境适配；systemctl 不可用时按 supervisor-hosting 项目根校验的同款风格打印可读错误并拒绝启动。
- 日志文件布局不变：supervisor.log / fenixd.log 照旧写文件（读侧零改动），stdout 额外进 journald 备查。

## 反目标（出现即失败）

- `systemctl stop` / 重启造成在飞 run 被硬杀（排水语义被破坏）。
- dashboard 继承 claude 会话环境被 claude-watchdog 误绑自杀（CLAUDE_PID 类事故复发）。
- 双托管并存窗口：unit 已启用、旧 tmux session 还在 → 同项目双 daemon。
- 熔断被架空：supervisor 连败熔断退出后被 systemd 无限拉回形成告警风暴。

## 设计要点

### unit 形态

- 每项目一条静态 unit：`fenixd-<项目名>.service`（项目名做文件名安全化），`WorkingDirectory=<项目根>`，`ExecStart=python3 .fenix/bin/fenixd_supervisor.py --project-root <项目根>`。**daemon 必须仍是 supervisor 的子进程**（唯一托管启动路径契约保持，systemd 监督的对象是 supervisor，不是 daemon）。
- dashboard 一条：`fenix-dashboard.service`，WorkingDirectory=框架主树，`ExecStart=python3 .fenix/bin/fenix_dashboard.py --serve`。
- **Restart 策略：`Restart=on-failure` + 退出码协议**（builder check 定案 #1——`Restart=always` 会结构性架空熔断：新 pid 清旧熔断标记→再拉→再熔断→再拉，且每轮发 critical 告警）。supervisor 的四条**有意退出**路径以约定退出码退出、systemd 不拉回：
  - 退出码 0：停机信号收尾、stop 旗标在场退出（显式停止语义保持）；
  - `SuccessExitStatus` 追加的专用码（建议 75）：熔断退出（supervisor_fused）、兜底收尸/收编超限放弃看护——「设计内放弃」不等于崩溃，恢复均为人工（清熔断标记 / 处置告警后 `systemctl start`）。
  - 其余一切退出形态（SIGKILL、异常非零码）→ systemd 拉回。`StartLimitIntervalSec`/`StartLimitBurst` 保留为 crash-loop 最后兜底。
- `WantedBy=multi-user.target`，安装即 `systemctl enable --now`。
- 停机语义：supervisor 已有 SIGTERM/SIGINT 转发收尾（SIGTERM→daemon→动态 sigkill_wait（drain+120）→超时 SIGKILL），`ExecStop` 无需自造协议；`TimeoutStopSec` ≥ 排水上界（建议 2100s），`KillMode=mixed`（先 TERM 主进程走优雅链，超时后收编全组兜底孤儿 claude）。

### unit 运行环境（builder check 定案 #2——不能「默认从简」）

生产链必需的 env 以 **`EnvironmentFile`（0600 root 属主，如 `/etc/fenixd/fenixd.env`）** 承载，不裸写进 unit（unit 文件全局可读，密钥不可入）。键集来源 = 切换时刻从在跑 daemon/dashboard 的 `/proc/<pid>/environ` **机械捕获**，套会话身份 denylist：

- **剥离**（会话身份/监视绑定键，入库即事故）：`CLAUDE_PID`、`CLAUDECODE`、`CLAUDE_CODE_*`、`AI_AGENT`、`IS_SANDBOX`、`GIT_ASKPASS`、`CLAUDE_CODE_MESSAGING_*`、`CLAUDE_CODE_SSE_PORT` 等全部会话专属键。
- **保留**（已实证在跑进程携带、agent 网络路径候选）：`PATH`（须含 `/root/.local/bin`——claude CLI 落点，systemd 默认 PATH 不含）、`HOME=/root`、`LANG`、`HTTP_PROXY`/`HTTPS_PROXY`/`http_proxy`/`https_proxy`（实测指向 clash `http://127.0.0.1:20122`，含小写空串形态原样保留）、`ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_DEFAULT_*_MODEL(_NAME)`、`API_TIMEOUT_MS`。
- **dashboard unit 额外固定键：`FENIX_DASHBOARD_DETACH=1`**（builder check 定案 #7，必设）——server.py `_bind_parent_lifecycle` 在 PPID==1 且该变量缺位时**拒绝启动 exit(1)**，systemd unit 主进程 PPID 恒为 1，不设则 unit 无限崩溃循环。设了 DETACH=1 后 CLAUDE_PID 缺位即走「纯人长驻豁免」分支（既有判定，成立）。
- 捕获动作交付为脚本（env 捕获 → denylist 过滤 → 生成 EnvironmentFile 候选稿供人工审核），切换冒烟验证：unit 起来后跑一次最小 agent spawn（`claude --version` + 网关健康探测），失败即回滚。

### 代码迁移点（builder 落地清单）

- `core/fenix_session.py start_daemon(root)`：tmux new-session → unit 缺失时生成安装 + `systemctl enable --now`；幂等语义保持（已在运行返回 `already=True`）。
- `core/fenix_session.py stop_daemon(root)` **双轨**（builder check 定案 #5/#6）：
  - unit 已安装：`systemctl stop --no-block` + **沿用既有 ≤30s 轮询确认**（保现行快速停机契约与 dashboard stop 端点 30s 预算——同步 `systemctl stop` 最坏挂 2100s 不可接受）；轮询超时按现行语义对 /proc 定位的残留进程补 SIGKILL 收口。
  - unit 未装但进程在跑（「managed 但无 unit」态，含迁移期与人工直启）：**保留既有直接信号链**（写 stop 旗标 → SIGTERM daemon → 等待 → 超时 SIGKILL），不得谎报成功。
  - tmux kill-session 兜底退役；步骤⑤「无论成败清除 stop 旗标」语义保持。
- `bin/fenixd_supervisor.py`：四条有意退出路径落实退出码协议（0 / 75），crash 路径退出码不变。
- `core/hook_engine.py` 内置 `pushed → restart-dashboard` 动作（builder check 定案 #4——它用 `tmux has-session`+`respawn-window`，按「kill-session」关键词搜不到，易漏迁）：执行侧迁 `systemctl restart fenix-dashboard`；unit 未安装时维持既有「静默 skip」语义（与 tmux 无会话时对齐）；用户 config 中 legacy `target` 键（tmux 会话名）容忍存在但不再消费。
- `core/dashboard/server.py`：**unit 承载实例加不可接管豁免**（builder check 定案 #8）——父进程为 PID 1 的常驻实例不可被手工 `--serve` 接管（SIGTERM），防「接管→systemd 拉回→反向接管」的生产闪断；这是 `_parent_is_tmux_server` 豁免的 systemd 对应物。
- install-hosting 端点同步迁移（复用 start/stop，不绕过）。
- `skills/fenix-setup/SKILL.md`、`skills/fenix-dashboard/SKILL.md` 托管/启动/重启配方改 systemctl 语义（含「看现场」指引：journalctl + 既有日志文件）。
- `core/fenix_session.py` 的 tmux 回退判定退役（`is_running` 主判定扫 /proc，本就不依赖 tmux）。

### 一次性搬迁编排（builder check 定案 #3——修正初稿顺序错误）

初稿「先 enable --now 再拆旧链」**不可行**：新 supervisor 撞单实例锁反复退出、dashboard 撞 8787 端口接管守卫进崩溃循环，且迁移后的 `stop_daemon` 对「unit 不拥有的旧 tmux 链」无能为力（`systemctl stop` 对未启动 unit 是 no-op）。正确编排（搬迁脚本 `bin/migrate_to_systemd.py`，独立于迁移后启停函数，支持 `--dry-run`）：

1. 写 unit 文件 + 生成 EnvironmentFile 候选稿（**不 enable**）；
2. 用**旧语义专用路径**拆旧 tmux 链（迁移前代码语义：写 stop 旗标 → SIGTERM → 确认；dashboard 旧实例直接 kill pid 等端口释放）；
3. `systemctl enable --now` 两条 unit；
4. 验收四件套（见下）+ env 冒烟（agent spawn）。

实际执行切换是**人工步骤**（拆的是在跑 daemon 本尊，Agent 不可代拆）：脚本落位 + dry-run 预演为 Agent 任务，真切换由人工执行并记入 `.fenix/todo.md`。

## 验收配方

1. `kill -9` supervisor / daemon / dashboard → 各自被 systemd 拉回（on-failure 对异常退出生效）。
2. 熔断路径：人为制造连败 → supervisor 退出码 75 → unit 不拉回，unit 状态 inactive（非 failed）。
3. `systemctl stop` ≤30s 有界收口，停机干净（无孤儿 claude、无残留进程）；stop 旗标在场 supervisor 退出码 0 不被拉回。
4. 「managed 但无 unit」态 stop 走直接信号链成功。
5. pushed → restart-dashboard 在 unit 承载下重启成功；unit 缺席时静默 skip 不报错。
6. dashboard unit（PPID=1、DETACH=1）正常启动；手工 `--serve` 实例对 unit 承载实例的接管被豁免拒绝。
7. 搬迁脚本 dry-run 输出正确编排且无副作用；真切换后四件套验收全绿。

## 留给 builder

- unit 模板其余字段（Nice/OOMScoreAdjust 等默认从简）与 unit 名安全化规则。
- 测试如何 fake systemctl（PATH 注入假可执行 / monkeypatch），既有测试对 tmux 承载的迁移。
- EnvironmentFile 捕获脚本的具体落点与 denylist 键集的完备化（以正则前缀族覆盖，不只枚举）。
- dashboard.log 文件去留（journald 已覆盖；如有读侧依赖保留 ExecStart 内重定向）。

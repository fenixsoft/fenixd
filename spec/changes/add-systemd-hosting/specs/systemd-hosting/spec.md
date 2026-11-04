## ADDED Requirements

### Requirement: systemd unit 形态与安装

框架 MUST 为每个项目生成一条静态 unit `fenixd-<项目名>.service`（项目名做文件名安全化），`WorkingDirectory=<项目根>`，`ExecStart=python3 .fenix/bin/fenixd_supervisor.py --project-root <项目根>`；并为框架主树生成 `fenix-dashboard.service`（`ExecStart=python3 .fenix/bin/fenix_dashboard.py --serve`）。daemon MUST 仍是 supervisor 的子进程（systemd 监督对象是 supervisor，不是 daemon）。unit 安装即 `systemctl enable --now`，`WantedBy=multi-user.target`（开机自启）。安装操作 MUST 幂等：unit 已存在且服务活跃时重复安装 MUST NOT 重建或重启服务。systemctl 不可用或无权限时 MUST 打印可读错误并拒绝启动，MUST NOT 静默降级为 tmux。

#### Scenario: 启动未托管项目安装并启用 unit

- **WHEN** 对 `stopped` 项目调用启动（unit 不存在）
- **THEN** `fenixd-<项目名>.service` 被写入 systemd 目录并 `enable --now`，supervisor 进程出现且 daemon 的父进程是该 supervisor

#### Scenario: 已活跃项目重复安装幂等

- **WHEN** 对 unit 已启用且服务活跃的项目再次执行安装
- **THEN** 不重建 unit、不重启服务，返回 `already=True`

#### Scenario: systemctl 不可用拒绝启动

- **WHEN** `systemctl` 命令不可用（非 systemd 环境）时调用启动
- **THEN** 返回可读错误（含「需要 systemd」指引），不产生任何 daemon/supervisor 进程，MUST NOT 回退创建 tmux session

### Requirement: 重启策略与 supervisor 退出码协议

项目 unit 与 `fenix-dashboard.service` 的重启策略 MUST 均为 `Restart=on-failure`，项目 unit 并以 `SuccessExitStatus` 声明 supervisor 有意退出的专用码（dashboard 无熔断/放弃看护语义，不适用退出码协议，SIGTERM 干净收尾退出 0 不拉回即满足）。supervisor 的四条有意退出路径退出码 MUST 为：停机信号收尾与 stop 旗标在场退出 → 0；熔断退出（supervisor_fused）与兜底收尸/收编超限放弃看护 → 专用码 75。退出码 0 与 75 的退出 MUST NOT 被 systemd 拉回；其余一切退出形态（SIGKILL、异常非零）MUST 被 systemd 拉回——含 dashboard 进程崩溃（目标「supervisor、daemon、dashboard 全部由 systemd 自动拉回」要求覆盖 dashboard 单独崩溃）。`StartLimitIntervalSec`/`StartLimitBurst` 在两类 unit 上 MUST 均配置为 crash-loop 最后兜底。

#### Scenario: supervisor 被 kill -9 后自动拉回

- **WHEN** supervisor 进程被 `kill -9`（unit 活跃）
- **THEN** systemd 检测到异常退出并重新拉起 supervisor，daemon 由新 supervisor 拉回，托管态恢复 `managed`

#### Scenario: 熔断退出不被拉回

- **WHEN** supervisor 因 restart 连败写 `supervisor_fused` 并以退出码 75 退出
- **THEN** unit 状态为 inactive（非 failed），systemd 不重新拉起；告警仅此一条，无拉回风暴

#### Scenario: stop 旗标退出不被拉回

- **WHEN** supervisor 因 `.fenix/stop` 旗标在场以退出码 0 退出（非 systemctl stop 触发）
- **THEN** systemd 不重新拉起 supervisor，unit 状态 inactive

#### Scenario: dashboard 进程崩溃被拉回

- **WHEN** `fenix-dashboard.service` 活跃时 dashboard 进程异常退出（非零码崩溃）
- **THEN** systemd 按 `Restart=on-failure` 重新拉起 dashboard，:8787 恢复监听

### Requirement: unit 运行环境承载

unit 运行环境 MUST 经 `EnvironmentFile`（0600 root 属主）承载，MUST NOT 将密钥裸写进 unit 文件（全局可读）。框架 MUST 提供 env 捕获脚本：从在跑 daemon/dashboard 的 `/proc/<pid>/environ` 机械捕获候选键集，并套会话身份 denylist 过滤——剥离 `CLAUDE_PID`、`CLAUDECODE`、`CLAUDE_CODE_*` 前缀族、`AI_AGENT`、`IS_SANDBOX`、`GIT_ASKPASS` 等会话专属键；保留 `PATH`（须含 `/root/.local/bin`）、`HOME`、`LANG`、代理四件套（`HTTP_PROXY`/`HTTPS_PROXY`/`http_proxy`/`https_proxy` 值原样保留）、`ANTHROPIC_BASE_URL`、`ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_DEFAULT_*`、`API_TIMEOUT_MS`。dashboard unit MUST 显式设置 `FENIX_DASHBOARD_DETACH=1`（PPID==1 且该变量缺位时 serve 拒绝启动 exit(1)，systemd unit 主进程 PPID 恒为 1）。

#### Scenario: 捕获脚本剥离会话身份键

- **WHEN** 捕获脚本读取带 `CLAUDE_PID`、`CLAUDE_CODE_SESSION_ID`、`ANTHROPIC_AUTH_TOKEN`、`HTTPS_PROXY` 的进程环境并生成 EnvironmentFile 候选稿
- **THEN** 候选稿不含 `CLAUDE_PID`、`CLAUDE_CODE_SESSION_ID` 及任何 `CLAUDE_CODE_*` 前缀键，且含 `ANTHROPIC_AUTH_TOKEN`、`HTTPS_PROXY` 原值

#### Scenario: dashboard unit 带 DETACH 正常启动

- **WHEN** `fenix-dashboard.service` 在 systemd 下启动（主进程 PPID=1）
- **THEN** 因 `FENIX_DASHBOARD_DETACH=1` 在位，serve 正常监听 :8787，且进程环境中无 `CLAUDE_PID`（claude-watchdog 不绑定，长驻豁免成立）

### Requirement: 托管停止的 systemctl 双轨语义

stop 路径 MUST 按 unit 接管状态双轨执行：unit 已安装时，写 `.fenix/stop` 后执行 `systemctl stop --no-block`，沿用既有 ≤30 秒轮询确认（MUST NOT 同步等待 `systemctl stop`——其最坏等待为排水上界量级），轮询超时对入口快照中仍存活的残留 supervisor/daemon 进程补发 SIGKILL 收口（快照对象为 stop 入口一次经 `/proc` 定位的项目进程集合，超时兜底 MUST 只杀快照内残留、MUST NOT 重新扫描——既有并发安全契约保持，防把并发 start 新拉起的进程误杀）；unit 未安装但进程在跑（managed-but-no-unit 态）时，MUST 保留既有直接信号链（写 stop 旗标 → SIGTERM daemon → 轮询等待 → 超时补 SIGKILL），MUST NOT 因 `systemctl stop` 对未启动 unit 是 no-op 而谎报成功。两条轨 MUST 都以「无论成败清除 `.fenix/stop`」收尾；停止未运行项目 MUST 幂等返回成功。

#### Scenario: unit 承载项目优雅收口

- **WHEN** unit 已安装且服务活跃的项目调用 stop
- **THEN** supervisor 收到 SIGTERM 走既有转发收尾（SIGTERM daemon → 排水窗），30 秒内双双退出，返回 `{"ok": true}`，结束后 `.fenix/stop` 不存在且进程全无

#### Scenario: 轮询超时补杀不残留孤儿

- **WHEN** stop 后 30 秒内 daemon 未退出（深排水）
- **THEN** 对残留进程补发 SIGKILL，结束后无孤儿 claude/daemon/supervisor，返回成功

#### Scenario: managed 但无 unit 时走直接信号链

- **WHEN** supervisor/daemon 进程在跑但 unit 未安装（如迁移期或 unit 被手工卸载），调用 stop
- **THEN** 按既有直接信号链停止成功（SIGTERM → 等待 → 超时 SIGKILL），返回成功且进程全无；MUST NOT 出现「systemctl stop no-op 却报成功」的假停止

### Requirement: dashboard unit 承载实例的接管豁免

dashboard serve MUST 将「父进程为 PID 1 的常驻实例」与 tmux 承载常驻实例同等对待为不可接管：启动方（含手工 `--serve`、agent 自测实例）MUST NOT 对其执行 SIGTERM 接管，MUST 返回「已有常驻实例（unit 承载）」类可读失败。防止「手工实例接管 → systemd 拉回 → 反向接管」的生产实例闪断循环。

#### Scenario: 手工 serve 不接管 unit 承载实例

- **WHEN** `fenix-dashboard.service` 活跃（:8787 在听），另以手工 `python3 fenix_dashboard.py --serve` 启动实例
- **THEN** 手工实例识别到 unit 承载常驻实例后拒绝接管并以可读信息退出，生产实例不受影响（不闪断）

### Requirement: restart-dashboard 内置动作迁移

`core/hook_engine.py` 内置默认条目 `pushed → restart-dashboard` 的执行侧 MUST 从 tmux 会话操作（has-session/respawn-window）迁移为 `systemctl restart fenix-dashboard`；`fenix-dashboard` unit 未安装时 MUST 维持既有「静默 skip」语义（与 tmux 无会话时对齐），MUST NOT 报错或产生失败告警。用户 config 中该动作的 legacy `target` 键（tmux 会话名）MUST 容忍存在但不再消费。

#### Scenario: unit 承载下 pushed 后重启 dashboard

- **WHEN** `fenix-dashboard` unit 活跃，某 SPEC 进入 `pushed` 触发内置 restart-dashboard 动作
- **THEN** dashboard 进程被 systemd 重启，:8787 恢复监听，hook 审计记录成功

#### Scenario: unit 未安装时静默 skip

- **WHEN** `fenix-dashboard` unit 未安装，触发 restart-dashboard 动作
- **THEN** 审计记录为 skipped（静默），不产生失败告警

### Requirement: 一次性搬迁编排

框架 MUST 提供 `bin/migrate_to_systemd.py`（支持 `--dry-run`），编排顺序 MUST 为：① 写 unit 文件与 EnvironmentFile 候选稿（**不 enable**）；② 经**旧语义专用路径**拆旧 tmux 承载链（此时迁移后的 start/stop 对 unit 不拥有的旧链无能为力，MUST NOT 复用迁移后启停函数；dashboard 旧实例按旧配方直接 kill pid 并等待端口释放）；③ `systemctl enable --now` 两条 unit；④ 验收（进程/端口/自愈/env 冒烟）。脚本 MUST 保证不出现「unit 已启用而旧 tmux 链仍在」的双托管窗口。真实切换 MUST 为人工步骤（拆的是在跑 daemon 本尊）：Agent 交付脚本落位 + dry-run 预演，人工执行真切换。

#### Scenario: dry-run 无副作用

- **WHEN** 以 `--dry-run` 执行搬迁脚本
- **THEN** 输出完整编排步骤清单（含将写入的 unit 内容与 env 候选稿摘要），不写 unit、不动进程、不 enable

#### Scenario: 真切换无双托管窗口

- **WHEN** 人工对 managed 项目执行搬迁脚本（非 dry-run）
- **THEN** 旧 tmux supervisor/daemon 先行退场且旧 dashboard 实例退出并释放 8787，此后才 enable --now；全程任意时刻至多一条托管链、一个 :8787 实例

## Why

`restart-daemon` 是「合并新代码后让其生效」的常规手段，但它在任何未经手工托管的项目上都是**静默失效**的：09-12 00:08 fenix-server 的 `done` hook 写入 `.fenix/restart_request` 并回报 `status: success`，而该项目根下**根本没有 supervisor 进程**——文件挂到今天仍在，daemon 跑着 Sep 10 的旧代码，唯一信号是 10 分钟后的一条 critical 告警。

三个独立缺陷叠加成这条断裂的托管链：

1. **`/fenix-setup` 从不用 supervisor 启动 daemon**（`skills/fenix-setup/SKILL.md:154` 直接 `tmux new-session ... python3 .fenix/fenixd.py`；`git log -S 'fenixd_supervisor' -- skills/fenix-setup/SKILL.md` 零命中）。而 `README.md:166`、`docs/help/04-cli.md:59`、`docs/help/06-governance.md:100`、`docs/help/07-safeguards.md:71,87` 一致声称「daemon 由 supervisor 托管，而非 tmux」。文档是契约，实现是反的。
2. **`bin/fenixd_supervisor.py:29` 的 `PROJECT_ROOT = Path(__file__).resolve().parent.parent` 会跟随 `.fenix/bin -> <主树>/bin` 软链**，把任何子项目的 supervisor 强行绑回主树。实测（cwd=/root/fenix-server）：`.fenix/bin/fenixd_supervisor.py → /root/fenixd/bin/fenixd_supervisor.py → PROJECT_ROOT=/root/fenixd`。后果不只是「无效」而是**有害**：它会把 `/root/fenixd` 当作目标，拉起第二个 daemon（被 `daemon.lock` flock 拒退），进入 3 秒一轮的无限重启空转，并每轮 `RESTART_REQUEST.unlink()` **吞掉主树的重启请求**，同时污染主树 `daemon_started` / `supervisor_runtime.json`。而 `core/admin_monitor.py:951` 的 `recommended_action` 恰恰建议用户去执行这条命令。
3. **没有人管 supervisor 自己**。主树 supervisor（PID 3325244）于 2026-09-06T03:20 启动，早于同日 12:31 落地的 `_write_supervisor_runtime` 自报特性，因此至今不写 `supervisor_runtime.json`；daemon 已在 `fenixd.log` 连报 4 次 WARNING（最新 2026-09-12T00:47）无人处置。看门狗没有看门狗。

同时存在两处**检测盲区**让上述状态长期不可见：`fenixd.py:_check_supervisor_drain_consistency()` 以 `if drain_seconds <= 0: return` 开头，`admin.shutdown_drain_seconds: 0` 的项目（fenix-server / scheduling-showcase 皆然）整段自检被旁路，即便 `supervisor_runtime.json` 缺失也不报警；`core/fenix_session.py:84` 的存活检测有意同时认 `fenixd.py` 与 `fenixd_supervisor` 两种 cmdline（注释写明「覆盖 tmux 与直启两种模式」），把「无 supervisor」合法化成一个不报错的状态。`core/hook_engine.py:_action_restart_daemon` 只验证「文件写成功」，不验证「有没有消费方」。

现在修的理由：这是**在多项目拓扑下必然复发**的结构性缺陷，而非一次性事故——每个新 `/fenix-setup` 出来的项目都会带着一条断掉的托管链上线，而用户看到的是一句「supervisor 将执行优雅重启」。

## What Changes

- **BREAKING**：`bin/fenixd_supervisor.py` 的目标项目根改由 `--project-root` 参数 / `FENIX_PROJECT_ROOT` 环境变量决定，缺省回退 `Path.cwd()`；彻底移除 `Path(__file__).resolve()` 派生路径。启动守卫校验：解析根下必须存在 `.fenix/`，否则拒绝启动并给出可读错误。
- **BREAKING**：daemon 与 supervisor 的唯一合法启动路径统一为 supervisor 托管。`core/fenix_session.py:start_daemon()` 改为在项目唯一 tmux session 内拉起 `fenixd_supervisor.py`（tmux 降级为「脱离终端的承载手段」，不再是 daemon 的父进程）；`stop_daemon()` 改为「写 `.fenix/stop` + 触发一次计划性重启」让 supervisor 收口退出，不再直接杀 daemon。
- `skills/fenix-setup/SKILL.md` 第 7 步改为经 supervisor 启动，与文档契约对齐。
- supervisor 新增自报扩展：除 `sigkill_wait` / `started_at` 外，写入自身脚本的 `script_hash` 与 `pid`。
- daemon 启动自检拆为两条独立判定：**supervisor 存在性**（与 `shutdown_drain_seconds` 无关，0 值也必须查）与 **drain 一致性**（仅 drain>0 查）；存在性失败时落 escalation 告警而非仅 WARNING。
- `core/fenix_session.py` 新增 `supervisor_running(root)` 与托管态判定，daemon 状态区分 `running`（已托管）/ `unmanaged`（裸 daemon）/ `stopped`。
- `core/hook_engine.py:_action_restart_daemon`：写请求后校验消费方存在，不存在时返回 failure 并触发既有 `_alert_failure`，不再报假成功。
- `core/admin_monitor.py:_detect_restart_failure` 的 `recommended_action` 改为按「supervisor 是否存在」分支给出安全建议，移除「手动启动 `.fenix/bin/fenixd_supervisor.py`」这条在多项目拓扑下有害的指引。
- Dashboard 项目页/概览卡片对 `unmanaged` 项目提供「安装 supervisor 托管」操作（停止裸 daemon → 经 supervisor 重启），作为存量项目（fenix-server、scheduling-showcase）的一次性修复路径。

## Capabilities

### New Capabilities
- `supervisor-hosting`: supervisor 的启动契约（项目根解析与守卫）、唯一托管路径的启停协议、`supervisor_runtime.json` 自报扩展（pid / script_hash）、托管态判定（running / unmanaged / stopped）、托管缺失的检测与告警、存量项目「安装托管」操作。

### Modified Capabilities
- `project-lifecycle-control`: Dashboard 项目启停 MUST 经 supervisor 托管而非 tmux 直启 `fenixd.py`；停止语义由「杀 daemon」改为「让 supervisor 收口退出」。
- `daemon-health`: 每项目 daemon 存活判定 MUST 从「tmux session 命中」改为「托管态判定」，并 MUST 额外区分 `unmanaged`（进程在跑但无 supervisor）。
- `admin-health-monitor`: `restart_failed` 检测继续以 `restart_request` 超时为触发，但升级建议 MUST 先判定 supervisor 是否存在并按结果分支，不得给出会劫持其它项目的操作指引。

## Impact

- **代码**：`bin/fenixd_supervisor.py`（项目根解析 + 守卫 + 自报扩展）、`core/fenix_session.py`（start/stop 语义 + `supervisor_running` + 托管态）、`core/dashboard/server.py`（项目 restart 前置校验 + 安装托管端点）、`core/dashboard/data.py`（daemon 状态聚合）、`fenixd.py`（启动自检拆分 + 告警落盘）、`core/hook_engine.py`（restart-daemon 消费方校验）、`core/admin_monitor.py`（建议文案分支）。
- **技能**：`skills/fenix-setup/SKILL.md`（第 7 步启动命令）、`skills/fenix-status/SKILL.md`（托管态展示，如有涉及）。
- **文档**：`docs/help/04-cli.md`、`docs/help/06-governance.md`、`docs/help/07-safeguards.md`、`docs/help/08-dashboard.md`、`docs/help/09-config.md`、`docs/help/11-faq.md`、`README.md` —— 把「由 supervisor 托管」从**声称**变成**事实**，并补「托管态三态」与「安装托管」说明。
- **数据/兼容性**：`supervisor_runtime.json` 新增字段为向后兼容的增量键（读侧按缺失处理为「旧版 supervisor」）。旧的无 `--project-root` 启动方式在 cwd 等于项目根时行为不变。
- **存量现场**：`/root/fenix-server/.fenix/restart_request`（09-12 00:08 残留，daemon 仍跑 09-10 代码）与主树陈旧 supervisor 进程（PID 3325244，不写自报）为本 SPEC 的首批存量验证对象，但**不在实现阶段直接操作生产进程**，由落地后的「安装托管」操作与用户确认后处理。
- **非目标**：不引入 systemd / 外部进程管理器；不改变 daemon 自身的排水与恢复语义；不改动 `restart_request` 文件信号协议本身。

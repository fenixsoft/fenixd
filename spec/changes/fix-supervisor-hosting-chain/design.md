## Context

Fenixd 的进程拓扑有两条互相矛盾的历史线：

- **文档线**（`README.md:166`、`docs/help/04-cli.md:59`、`docs/help/06-governance.md:100`、`docs/help/07-safeguards.md:71,87`）自 `fix-admin-self-heal` 起宣称「daemon 由 supervisor 托管，而非 tmux」，理由是自杀式重启的根因——admin agent 是 daemon 的子进程，直接 kill daemon 会连带杀死自己，所以重启职责必须外置给独立进程。
- **实现线**（`skills/fenix-setup/SKILL.md:154`、`core/fenix_session.py:119-156`、`core/dashboard/server.py:1573`）从未跟上：`fenix-setup` 与 Dashboard 一直用 `tmux new-session ... python3 .fenix/fenixd.py` 直启。`git log -S 'fenixd_supervisor' -- skills/fenix-setup/SKILL.md` 零命中，说明这一偏离从 setup 技能诞生起就存在。

2026-09-12 的事故把这个矛盾变成钱：fenix-server 的 `done` hook 写 `.fenix/restart_request` 并回报成功，而该项目根下没有 supervisor——文件挂了 12 小时，daemon 跑着两天前的代码，唯一信号是 10 分钟后一条 critical 告警。

叠加的第二层是 `bin/fenixd_supervisor.py:29` 的 `PROJECT_ROOT = Path(__file__).resolve().parent.parent`。项目内 `.fenix/bin` 是指向框架主树 `<main>/bin` 的软链，`resolve()` 会跟随它，于是**任何子项目的 supervisor 都被绑定回主树**。实测（cwd=`/root/fenix-server`）：`.fenix/bin/fenixd_supervisor.py → /root/fenixd/bin/fenixd_supervisor.py → PROJECT_ROOT=/root/fenixd`。这使「手动补一个 supervisor」这条最自然的运维动作变成投毒：它会把 `/root/fenixd` 当目标，拉起第二个 daemon（被 `daemon.lock` flock 拒退），进入 3 秒一轮无限空转，并每轮 `RESTART_REQUEST.unlink()` **吞掉主树真正的重启请求**。而 `core/admin_monitor.py:951` 的建议文案恰好让用户去执行它。

第三层是 supervisor 自己没有生命周期：主树 supervisor（PID 3325244）启动于 2026-09-06T03:20，早于同日 12:31 落地的 `_write_supervisor_runtime` 自报特性，因此至今不写 `supervisor_runtime.json`，daemon 已连报 4 次 WARNING 无人处置。**看门狗没有看门狗。**

约束：改动必须保持「文件即状态」的架构性质，不引入数据库或外部进程管理器；不改变 daemon 自身的排水/恢复语义；不改变 `restart_request` 文件信号协议本身（它是 dashboard、hook、admin 三方共用的既有契约）。

## Goals / Non-Goals

**Goals:**

1. 让「daemon 由 supervisor 托管」从**声称**变成**事实**：setup 与 Dashboard 启停一律经 supervisor。
2. 让 supervisor 能在**任意项目根**正确运行，彻底移除 `Path(__file__).resolve()` 的软链跟随。
3. 让「无 supervisor」成为一个**可见且会被升级**的状态，而不是靠 10 分钟后孤零零一条 `restart_failed` 才发现。
4. 让已经断链的存量项目（fenix-server、scheduling-showcase、主树陈旧 supervisor）有一条**安全的一次性修复路径**。
5. 消除「用户照告警建议操作反而投毒主树」这一风险。

**Non-Goals:**

- 不引入 systemd / supervisor(3) / docker 等外部进程管理器。tmux 保留为「脱离终端的承载手段」。
- 不改动 daemon 的排水窗口（`admin.shutdown_drain_seconds`）与 boot recovery 语义。
- 不改动 `.fenix/restart_request` 的文件信号协议与 restart-daemon 的既有语义（只加消费方校验）。
- 不实现 supervisor 的自动热重载/自 re-exec。陈旧 supervisor 通过显式的「安装托管 / 重启托管」操作升级，不做隐式自杀重生。
- 不在实现阶段直接操作任何生产进程（本机三个项目的现场由用户确认后经新操作路径处置）。

## Decisions

### D1. supervisor 的项目根：显式参数优先 + cwd 兜底，废弃 `__file__` 派生

**决策**：`PROJECT_ROOT` 按 `--project-root` > `FENIX_PROJECT_ROOT` > `Path.cwd()` 解析，解析后校验存在 `.fenix/`，并规范化（`expanduser().resolve()`）。

**理由**：`fenixd.py:37-39` 已经给出了正确模式的先例——它用 `Path(__file__).absolute()`（**不跟随软链**）保证 `FENIX_DIR` 落在调用方项目的 `.fenix/` 内。supervisor 完全可以照抄这个模式（`__file__.absolute().parent.parent.parent`），但那样仍然把「脚本物理位置」当作隐式输入。显式参数 + cwd 兜底的好处是：调用方（`fenix_session.start_daemon`、运维手工、未来的其它入口）必须**说出**目标是谁，而 cwd 兜底保证「cd 到项目根再启动」这条最朴素的操作仍然有效。

**备选方案**：
- 仅 `Path.cwd()`：最简，但没有显式锚点，跨目录调用时依赖调用方自觉。
- `Path(__file__).absolute()` 三跳：最小 diff，但错误时表现为「静默认错项目」而非「拒绝启动」——正是本次事故的失效模式。
- 读 `.fenix/config.yaml` 的 `project.root`：config 本身在 `.fenix/` 下，循环依赖，且 config 缺失时无解。

### D2. 启动/停止语义：supervisor 是 daemon 的父进程，tmux 只负责脱离终端

**决策**：`start_daemon` 的 session 命令改为 `cd <root> && python3 .fenix/bin/fenixd_supervisor.py --project-root <root> >> .fenix/logs/supervisor.log 2>&1`。`stop_daemon` 改为「写 `.fenix/stop` → SIGTERM daemon → 等 daemon 与 supervisor 双双退出 → 超时 kill session 并补 SIGKILL → 清 `.fenix/stop`」。

**理由**：这是唯一能让「supervisor 无论 daemon 何时崩溃都能拉起」成立的拓扑——supervisor 必须是父进程，否则它无法 `proc.poll()` 感知退出。tmux 在此之后只是「把进程从终端 detach 出来」的手段，与它是否承载 daemon 无关。

**停止为什么不用 `restart_request`**：计划性重启路径（`.fenix/restart_request` 在册）会让 daemon 进入 `shutdown_drain_seconds` 排水，主树配的是 1800s——对一个「停止」按钮不可接受。而 `.fenix/stop` + SIGTERM 走的是**非计划 SIGTERM 快速停机**语义（`interrupt-recovery-preserve` 明确保留该分支逐字节不变），秒级收口。supervisor 的 `main()` 在 daemon 退出后检查 `STOP_FLAG` 即自行退出，这是现成的、无需新信号的路径。

**备选方案**：
- 只写 `.fenix/stop` 不 SIGTERM：supervisor 只在「主循环开头」与「daemon 退出后」检查 stop flag，daemon 不死它就不看，停止会挂住。
- 直接 kill session：会把 supervisor 与 daemon 一起 SIGHUP 掉，丢失优雅关闭清理，且若 supervisor 跑在 session 外则 daemon 成孤儿。
- 给 supervisor 注册 SIGTERM handler：需要新代码且要处理「收到 SIGTERM 时 daemon 还在跑」的级联，不如复用现有 stop flag。

### D3. 托管态三态判定：`managed` / `unmanaged` / `stopped`

**决策**：`core/fenix_session.py` 新增 `supervisor_running(root)` 与 `hosting_state(root)`；`unmanaged` = 有 daemon 进程但无 supervisor。

**理由**：现行 `is_running` 返回布尔，把「有 daemon 但没人管」和「完全没跑」压成同一个 `running`，导致仪表盘、admin、hook 都看不出断链。`unmanaged` 是本次事故的**核心可观测缺口**，必须成为一等状态。

**为何复用 `/proc` 扫描而非引入 pidfile**：`_daemon_procs_under` 已经建立了「cwd + cmdline」的判定范式并被 `is_running` 使用；pidfile 会引入陈旧/竞态问题。supervisor 的进程身份用同样的方式判定即可。

### D4. supervisor 存在性检测与 drain 一致性检测拆分

**决策**：`fenixd.py:_check_supervisor_drain_consistency` 拆为两项独立判定。存在性项**无条件执行**（与 `shutdown_drain_seconds` 无关）；drain 一致性项维持 `drain > 0` 前置条件。存在性失败 → WARNING + `signal_type: supervisor_missing` 的 major escalation 告警（按未处置去重）。

**理由**：`if drain_seconds <= 0: return` 是本项目自造的盲区——`drain=0` 的项目（fenix-server、scheduling-showcase 都是）恰恰是最容易没有 supervisor 的存量项目。且「无 supervisor」的危害远不止排水截断（requests 无人消费、重启永远不生效），不应被挂在「排水窗口」这个子议题下。

### D5. 告警建议文案按托管态分支

**决策**：`admin_monitor._detect_restart_failure` 的 `recommended_action` 按 `hosting_state` 分支；`unmanaged`/`stopped` 时指引经 Dashboard「安装托管」或 `/fenix-setup`，**不再出现**「手动启动 `.fenix/bin/fenixd_supervisor.py`」。

**理由**：当前文案在本机的多项目拓扑下是**有害指令**（见 Context 第二层）。告警的价值取决于建议动作是否安全，一条会导致主树重启请求被吞的指令比没有建议更糟。

### D6. 存量修复路径 = Dashboard「安装托管」端点

**决策**：新增 `POST /api/projects/<name>/install-hosting`，语义为「停裸 daemon → 经 supervisor 启动」，内部复用 `stop_daemon`/`start_daemon`，不绕过它们直接操作进程。

**理由**：存量项目不能靠等下一次 `/fenix-setup`（用户未必会重跑）。把它做成一个幂等的、可在仪表盘点一下的操作，且强制走同一对已被测试覆盖的启停函数，避免出现「第三套启停实现」。

**残留 `restart_request` 的处理**：不专门清理。安装托管后 supervisor 启动 → 立即可见陈旧的 `.fenix/restart_request` → SIGTERM daemon → 重启 → 清除请求。这恰好让「换上新代码」这个原始诉求自动达成，比手工删除更符合语义（用户当初就是想重启）。

### D7. 不做 supervisor 自动自升级

**决策**：supervisor 陈旧（`script_hash` 与磁盘不一致）只做**检测与告警**，升级靠显式操作。

**理由**：自动 re-exec 需要处理「execv 时 daemon 子进程已存在」的接管问题（新代码进程不持有旧 `proc` 句柄，会立刻认为 daemon 不存在并再拉一个，撞 `daemon.lock`），风险和复杂度都不小。而 supervisor 停留在旧代码的实际后果（排水被截断）远低于「自动重生产生双 daemon」的后果。显式操作 + 明确告警是更合适的风险/收益比。

## Risks / Trade-offs

- **[supervisor 成为单点：supervisor 自己崩溃则 daemon 成孤儿]** → 这本来就是现状（裸 tmux daemon 更糟：连崩溃自动拉起都没有）。缓解：`hosting_state` 会在下一轮检测中把项目标为 `unmanaged` 并升级告警，使这种状态**可见**而非静默。真正的兜底（外部 init 系统）列入 Non-Goals。

- **[停止路径写 `.fenix/stop` 后若在清理前崩溃，项目会永久拒绝启动]** → `stop_daemon` 在 `finally` 语义下清除 stop 文件；且「安装托管/启动」路径 MUST 在启动前检查并清除陈旧的 `.fenix/stop`（陈旧判定：无对应存活进程）。落为 tasks 中的显式任务与测试。

- **[`unmanaged` 状态被下游误当作 `stopped`]** → 所有消费点（dashboard 卡片、admin 建议、hook 校验）都必须显式分支三态；tasks 中要求逐点核对，测试覆盖 `hosting=unmanaged` 时 `daemon` 仍为 `running`。

- **[`--project-root` 引入后，旧的启动命令（无参数）语义依赖 cwd]** → 旧命令在 cwd=项目根时行为与现状一致（这是文档与 docstring 既有的启动契约）；仅在 cwd 非项目根且无参数时才由守卫拒绝启动，属于**新增的显式失败**而非行为回归。

- **[supervisor 现在跑在 tmux session 内，session 被外部 kill 会连带杀死 supervisor 与 daemon]** → 停止路径已按「先 SIGTERM daemon 让其优雅退出」排序，正常路径不触发 kill-session；kill-session 仅作为超时兜底，且兜底后补发 SIGKILL 确保无孤儿。

- **[改 `start_daemon` 会让已托管项目暂时处于「daemon 有父 supervisor，而 supervisor 在 tmux 内」的新拓扑]** → 这正是目标拓扑；对主树需在落地后用「安装托管」重建一次进程树，tasks 中标注为验证项而非实现项。

## Migration Plan

1. **代码先行，现场不动**：本 SPEC 只改代码、技能与文档；不改任何运行中的生产进程。
2. **兼容期**：`supervisor_runtime.json` 新增键为增量读法（缺失按「旧版 supervisor」处理），旧 supervisor 进程不会因新代码报错。
3. **落地后由用户确认再处置现场**，顺序建议：
   - `/root/fenixd`（主树）：当前 supervisor 陈旧（无自报）。经 Dashboard「安装托管」重建 → 新 supervisor 写入完整自报 → daemon 自检 WARNING 消失。
   - `/root/fenix-server`：`unmanaged` + 残留 `restart_request`。安装托管后 supervisor 消费该请求 → daemon 换上新代码 → `restart_failed` 告警可通过既有处置流程关闭。
   - `/root/scheduling-showcase`：同样 `unmanaged`，无残留请求。
4. **回滚**：改动集中在 7 个文件；`--project-root` 有 cwd 兜底，回滚只需 `git revert`，磁盘状态（stop 文件、runtime json）均为可安全删除的运行时文件。

## Open Questions

- **`install-hosting` 对 `stopped` 项目的语义**：当前定为「等价于启动」。是否需要在 UI 上与「启动」按钮合并（即「启动」在任何非 `managed` 状态下都做安装托管）？倾向合并，但需在实现阶段确认 Dashboard 交互细节，避免出现两个语义重叠的按钮。
- **陈旧 `.fenix/stop` 的自动清理是否要更激进**（如启动时无条件删除，不做存活判定）？倾向保守：只在确认无存活进程时删，避免误删正在进行的停止操作留下的标记。
- **`supervisor_missing` 告警的 `severity` 定为 `major` 是否偏高**：对「项目在跑但从不受托管」而言这是持续性缺陷而非瞬时故障，`major` 可能持续占据告警面板。实现阶段需与既有告警降噪偏好核对，必要时降为 `warning`。

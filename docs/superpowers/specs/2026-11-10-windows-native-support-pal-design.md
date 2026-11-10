# fenixd Windows 原生支持架构评估（平台抽象层路线）

- 日期：2026-11-10
- 状态：评估定稿，待 builder check 与用户批准
- 性质：立项前评估（不包含实现计划；实现按 §7 SPEC 分解另行起草）
- 证据来源：三路侦察（知识域 30 条绑定规则 / 代码盘点 7 节 / Windows 映射调研 10 项），锚点已内嵌正文

---

## 1. 意图与动因

fenixd 深度依赖 Linux 机制（systemd 托管、进程组信号、flock、`/proc`），当前只能在 Linux 上运行。部分开发者以**原生 Windows 进程**运行 claude code 与 dsh；fenix harness 定位为它们的增强层，因此 fenixd 必须运行在**同一原生进程环境**。

- WSL2 路线今天已可用，但**不是本次目标**（用户定调：必须原生）。
- 参照物 1：claude code / dsh 的 Windows 支持方式 = Node 运行时自带跨平台 + 死守跨平台 API、零 POSIX 专属系统调用。fenix 是 Python，语言层面同样跨平台；差距不在语言，在**系统调用习惯**。
- 参照物 2：微软 LiteBox（v0.1，2026-10-07，Rust Library OS，主打"Windows 上跑未改动的 Linux 程序"）。**评估结论：拒绝用于 fenixd 本体**——fenixd 的核心职责是托管 claude code / dsh 子进程（信号、进程组、存活探测），若 fenixd 关在 LiteBox 的 Linux 气泡内则管不到气泡外的原生 Windows 进程，与需求根本矛盾。LiteBox 可作为远期验证沙箱场景的候选选项（非目标，不立项）。

## 2. 目标 / 非目标 / 反目标

**目标**
- G1：fenixd 全功能在原生 Windows 进程运行，**全功能对等**——daemon、dashboard、派发、实现、验证、裁决、审查、修复、自愈、知识管线全部可用。
- G2：平台差异全部封装在平台抽象层（PAL）内部，业务代码零平台分支。
- G3：抽象落地过程 Linux 行为零回归。

**非目标**
- Windows on Arm（x86-64 only）。
- Windows Server 集群/无人值守部署形态优化（当前场景是开发者工作机）。
- WSL2 路线的维护投入（已有能力不删除，但不新增）。
- LiteBox 沙箱验证场景（远期选项）。

**反目标（出现即架构失败）**
- 业务代码中散落 `if platform == win32` 分支。
- 一次性大爆炸替换（22.6 万行不可行）。
- SPEC-1 期间 Linux 侧任何可见行为变化。

## 3. 硬约束（用户定调，评估全程有效）

1. **不能影响当前 Linux 版本已支持的功能**。
2. **架构层面的平台抽象**：如 740 处信号调用点应抽象为对同一组 PAL API 的调用，平台判断与差异化兼容在 API 内部完成；禁止写 740 处 `if platform=win32`。
3. **分 SPEC 进行**：SPEC-1 先完成抽象 + Linux 平台实现，通过所有单元测试，合入主线；SPEC-2 再实现 Windows 平台后端。
4. **集成测试使用本机 dockur/windows 镜像**。已验证前置条件：`/dev/kvm` 在场（硬件加速可用）、`dockurr/windows:latest` 镜像就位、容器 `windows` 已运行（8006 web viewer、8889→3389 RDP 已映射）。

## 4. 现状盘点：Linux 依赖的真实分布

> 初扫印象（五簇 ~1370 处命中）经代码核实后修正如下——**真实改造面显著小于命中数**。

### 4.1 五簇实际版图

| 簇 | 命中→实际 | 真实形态 | 集中度 |
|---|---|---|---|
| 进程组信号 | ~583 | 核心击杀纪律已单源：`kill_process_group()`（core/proc_utils.py:235，SIGTERM→wait→SIGKILL 补刀）+ `guard_killpg()`（core/proc_utils.py:331，拒向自身进程组发信号，**有守卫测试钉死先例**）；`start_new_session=True` 约 38 处 spawn 面（runner.py×16、verify_contract×7、one_shot×7、regression×4、hook_engine×4 等）；PDEATHSIG 仅 1 处 ctypes libc（dashboard/server.py:597）；`signal.signal` 注册仅 3 处；信号常量面窄（SIGKILL/SIGTERM/SIGINT） | 高 |
| flock | 281→80 call sites（~30 文件） | 统一原语已存在：`with_file_lock(path, fn)`（core/fs_utils.py:125），但多数调用点自持 `open+flock` 未走单源；用途三类：状态读改写串行化（state_machine.py:1459/1481 `.STATE.md.lock`）、跨进程单飞（knowledge.py DistillManager / knowledge-rewrite.lock / knowledge-log.lock；verify-prepare.lock verify_contract.py:1373）、任务领取互斥（pm_engine/dispatch queue×10、repair_lane×12）；另 `FlockRotatingFileHandler`（core/logger.py） | 高（收敛后） |
| systemd | ~205 | 单缝 `_run_systemctl()`（core/systemd_hosting.py:101，list argv 不经 shell）；unit 渲染 `render_project_unit`（:481，Restart=on-failure + StartLimit + TimeoutStopSec=2100 + SuccessExitStatus=75 + KillMode=mixed）；EnvironmentFile 0600 原子写（:373）+ `/proc/<pid>/environ` 候选稿捕获（:184）；journalctl 仅 4 处错误提示文案，无程序化调用；一次性搬迁脚本 bin/migrate_to_systemd.py | 高 |
| /proc | 95 | 六类读法：cmdline 探活/身份（proc_utils.py:65、liveness.py:727）、stat 字段（proc_utils.py:76/119）、cwd readlink 归属（fenix_session.py:76、serving_registry.py:365、locks.py:424）、端口占用者定位＝`/proc/net/tcp` inode+fd 扫描（dashboard/server.py:213-267，无 lsof 依赖）、父进程 comm 判定（dashboard/server.py:401，ADR-178）、environ 捕获（systemd_hosting.py:184） | 中 |
| inotify | 5→**0** | `core/event_bus.py` 文档措辞写 inotify，实际实现是 2s checksum 轮询（`_watch_loop` event_bus.py:1059）——**此簇不存在**，直接跨平台；顺手修文档措辞 | — |

### 4.2 其他 POSIX 面（逐项核实）

- `os.fork`：**0 处**；`multiprocessing`：**0 处**（全链同步 subprocess；asyncio 子进程仅 verify_engine/cli_runner.py:405-415 两处）。
- `import pwd`：仅 core/git_env.py:21（git 子进程用户名推导，凭证双腿单源在 core/git_env.py）；termios/tty/pty/resource/grp：0 处。
- `pgrep -f`：4 处（liveness.py:674、v2_dev_server.py:557、locks.py:377/475）。
- bash/shell 包装：4 文件（verify_contract×5、pm_engine/verification/serving×3、hook_engine×2、dsh_adapter×1）+ cli_runner asyncio shell；shell 脚本：install.sh（依赖检查含 **tmux**、`~/.claude/skills` 软链、`~/.local/bin` 软链）、scripts/format_code.sh、scripts/package.sh、tests/integration/{run.sh,e2e.sh,checks/*}。
- 硬编码路径：`("/usr/bin/node","/usr/local/bin/node")` 候选（v2_dev_server.py:83）、`/etc/systemd/system`（systemd_hosting.py:41）、`~/.claude/` 族 18 处（含 mergeback.py:1321 的路径 munge 规则 `/`与`.`→`-`）、symlink 安装（claude_adapter.py:209 `dst.symlink_to(src)`）。
- os.O_* 专属：O_DIRECTORY×2（fs_utils.py:88、admin_stray_wip.py:481）、O_EXCL/O_APPEND 可平移。
- 测试基建：tests/ 平铺 **438 个 test_*.py**；pytest.ini `timeout_method = signal`（SIGALRM，POSIX 专属）；Linux 行为测试全部走 monkeypatch/mock 不触真环境（test_systemd_hosting.py:14 注释明示）；Docker 集成测试基底 debian:bookworm-slim（tests/integration/run.sh 一键编排）。
- 守卫先例：grep 断言测试钉死"裸 `os.killpg` 零存在"（guard_killpg 配套）——**本次复用同一手法钉死"POSIX syscall 零散落"**。

### 4.3 跨域共性机制（PAL 设计的关键利好）

- 进程探测三源（存活/身份/归属）模式统一，识别 pattern 经 harness adapter `process_patterns()` 单源分发 4 处消费端。
- 原子写已有单源 fs_utils（但平行私有实现仍存 5+ 份：runner.py:6468 `_write_atomic`、claude_adapter.py:166、verify_scenarios.py:401、code_fix.py:276、state_machine.py:2951、supervisor:236/280）。
- killpg 单点守卫 + 守卫测试；systemctl 单缝；env 承载单源（PATH_BASELINE_DIRS/path_baseline_missing，core/systemd_hosting.py:215）；HOME 凭证双腿单源 core/git_env.py。

**结论：手术切口比命中数提示的干净得多。主要工作形态是"收敛存量 → 定义 PAL 面 → 平台后端化"，而非多点重写。**

## 5. PAL 设计（SPEC-1 核心交付）

### 5.1 分层与分发

- 新包 `core/platform/`：`api.py`（平台中立接口，类型化签名）+ `linux.py`（Linux 后端，现有行为逐条平移）+ `win32.py`（SPEC-2 占位）+ `__init__.py` 单点分发（import 时按 `sys.platform` 选后端）。
- **平台判断全库仅存在于 `core/platform/__init__.py` 一处**；业务代码只允许 `from core.platform import api as pal`。
- 向后兼容：`proc_utils` / `fs_utils` 等现有公开签名**原样保留**、内部转发 PAL——存量 438 个测试文件的调用点零改动，这是"Linux 零回归"的最小侵入保证。
- 静态防回潮：新增守卫测试，grep 断言 core/（除 `core/platform/linux.py`）零 `import fcntl`、`import pwd`、`killpg`、`os.setsid`、`prctl`、`/proc/`、`start_new_session`——沿用 guard_killpg 守卫测试的手法。**守卫零豁免清单**：因此全部直接消费端（14 个 `/proc/` 读点文件；`serving_registry.py:482/502` 的 `os.killpg(pid, 0)` 探活直调）必须在 SPEC-1 内迁移到 B 组接口（W4b），不以豁免换省事（builder check 定夺，2026-11-10）。

### 5.2 PAL API 面（六组）

**A. 进程生命周期**（linux=现行 killpg 语义；win32=Job Object kill-on-close + Toolhelp 快照兜底）
- `spawn_detached(cmd, cwd, env) -> Popen` —— 替代 38 处 `start_new_session=True`（win32: CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS/CREATE_NO_WINDOW + breakaway from job）。
- `terminate_graceful(proc, grace_s)` —— 现行 SIGTERM→grace→SIGKILL 纪律（win32: 协议级 shutdown 关 stdin/CTRL_BREAK_EVENT→grace→TerminateProcess；**语义差异显式记录在 docstring**）。
- `kill_tree(pid_or_proc, caller)` —— killpg 等价，guard 逻辑（拒自杀进程组）内置。
- `bind_to_parent(child)` —— PDEATHSIG 等价（win32: 手工 JobObject assign，dashboard/server.py:597 消费）。

**B. 进程情报**（linux=现行 /proc 解析平移；win32=psutil + create_time 身份守卫）
- `process_info(pid) -> {alive, cmdline, exe, cwd, ppid, start_token}`（start_token：linux=start ticks / win32=create_time，PID 复用防护统一在此）。
- `is_alive_with_identity(pid, identity)` —— 现行 cwd+cmdline 锚定语义（fenix_session/serving_registry/locks 共用）。
- `find_port_owner(port)` —— /proc/net/tcp 扫描 / win32 GetExtendedTcpTable（dashboard/server.py:213-267 平移）。
- `parent_comm(ppid)` —— ADR-178 宿主形态判据（dashboard/server.py:401）。
- `process_environ(pid)` —— /proc/<pid>/environ 捕获（systemd_hosting.py:184）；**win32 无对应物（无法读他进程 env），SPEC-2 以 spawn 时 env 快照替代，显式降级注记**。

**C. 文件锁**（先收敛、再后端化）
- `exclusive_lock(path, timeout_s)` / `try_lock(path)`。
- linux: flock LOCK_EX|LOCK_NB 语义逐点保持；win32: LockFileEx 思路（portalocker 同款）。注意建议锁→强制锁翻转风险（§8-R3），PAL 统一"锁 1 字节 @ offset 0"纪律。

**D. 托管 HostingProvider**
- `install_unit / start / stop / is_running / env_file / logs_hint`。
- linux: systemd 全语义平移（退出码 75 豁免、KillMode=mixed、EnvironmentFile 0600、stop 双轨）——SPEC-1 一字不动；win32: NSSM/WinSW 服务定义（SPEC-2 定型，见 §10）。

**E. 环境 / 用户 / 文件系统**
- `home_dir()`（HOME/USERPROFILE 单源，git_env 凭证双腿并入）。
- `current_user()`（pwd → getpass）。
- `ensure_link(src, dst)` —— symlink → junction → copy 降级链（win32 开发者模式/特权问题，claude_adapter.py:209 消费）。
- O_DIRECTORY try/except；O_BINARY/文本模式审计入口（§8-R4）。

**F. 测试基建**
- pytest `timeout_method` 平台化：linux 保持 `signal` 零变化；win32 配置用 `thread`（需评估 thread 方法 os._exit 副作用，SPEC-2 事项）；`tests/timeout-allowlist.yaml` 机制不变。

### 5.3 明确不需要抽象的

- event_bus（实为轮询，直接跨平台；仅修文档措辞）。
- 原子写 os.replace 模式本身（跨平台；win32 的 PermissionError 重试属 SPEC-2 细节）。
- 端口分配 `find_free_port`/`hold_free_port`（bind 逻辑跨平台；SO_REUSEADDR 语义差异属 SPEC-2 重验项）。

## 6. Windows 后端映射表（SPEC-2 预研结论）

| # | Linux 现状 | Windows 方案 | 库/API | 语义差异（一句话） |
|---|---|---|---|---|
| 1 | killpg+SIGKILL 清场 | Job Object（KILL_ON_JOB_CLOSE）为主 + Toolhelp 快照杀树兜底 | ctypes win32job / pywin32 | taskkill /T 对 leader 已退出的树静默漏杀（实测 rc=128），必须双保险 |
| 2 | SIGTERM 优雅终止 | 无 SIGTERM 等价物 | GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT) | `terminate()`=TerminateProcess 硬杀 exit 1，agent 无落盘退出机会 → 协议级 shutdown 重设计 |
| 3 | /proc 探活/身份 | psutil.Process + create_time 比对 | psutil 7.x | PID 复用频繁，必须 start_token 守卫；无僵尸态 |
| 4 | flock | LockFileEx（portalocker）| portalocker[win32] | 建议锁→强制锁；未协作读者 PermissionError；关闭句柄释放全部锁 |
| 5 | systemd unit | NSSM 包 python.exe 为服务（备 WinSW） | NSSM/WinSW | 无 SuccessExitStatus=75 / KillMode=mixed / `-`EnvFile 直接对应，需协议文档化映射 |
| 6 | PDEATHSIG | JobObject kill-on-close 手工 assign | ctypes | 子进程必须显式 breakaway 才能脱离 |
| 7 | pgrep -f | psutil.process_iter + process_patterns | psutil | pattern 单源已就绪，仅换枚举后端 |
| 8 | inotify | 不需要（实为轮询） | — | event_bus 零改动 |
| 9 | bash 安装链 | Git for Windows 的 bash.exe（与 claude code 官方要求一致） | CLAUDE_CODE_GIT_BASH_PATH 对齐 | 缺 bash 时语义漂移 PowerShell，探测必须显式 |
| 10 | symlink ~/.claude | 开发者模式 symlink → junction → copy | — | 无特权时 PermissionError，降级链兜底 |
| 11 | HOME/passwd 凭证双腿 | USERPROFILE + GCM | Git Credential Manager | wincred 已废弃并入 GCM；git_env 单源改造点 |
| 12 | 端口 SO_REUSEADDR | 重验 | — | Windows 语义更强可劫持端口，TIME_WAIT 行为不同 |
| 13 | journalctl 文案 | 事件日志/文件日志 | win32evtlog | 仅 4 处文案改动 |
| 14 | 孤儿判据 PPID==1 | 重定义（win32 reparent 非 1） | psutil | event_bus 前端 ppid===1 自灭、`_parent_is_pid1` 豁免均需平台化 |

## 7. SPEC 分解建议（约束 3 落地）

### SPEC-0：存量测试失败前置修复（builder check 发现 + 用户定夺，2026-11-10）

当前主线全量测试基线为 **12 failed / 10181 passed**（本机实测约 11m40s），并非全绿；至少 `test_logger_no_bypass` 为 core/ 真实违例（裸 `getLogger`，断言指认 dsh_session_tidy），非环境差异。用户定夺：**独立前置 SPEC（SPEC-0）先行清零存量失败，SPEC-1 验收维持"全量绿"原口径**。SPEC-0 与 SPEC-1 无代码耦合，可先行立项。

### SPEC-1：PAL + Linux 实现（本评估的直接后续）

| 工作项 | 内容 | 规模 |
|---|---|---|
| W1 | flock 80 处收敛到 `with_file_lock`（LOCK_EX\|LOCK_NB 语义逐点核对，含 FlockRotatingFileHandler）。**前置**：`with_file_lock` 先扩展可选参数（`nonblocking`/`timeout_s`，默认值保持现行阻塞 LOCK_EX 行为不变、向后兼容）——五个 NB fail-fast 消费点（verify_scenarios、regression、verify_contract、dashboard/server.py、verify_report）依赖它保语义，否则收敛即引入 Linux 挂死回归（builder check 定夺，2026-11-10） | L |
| W2 | 原子写平行实现 5+ 份收敛到 fs_utils 单源 | S |
| W3 | `core/platform/` 骨架：api.py 六组接口 + linux.py 平移 + `__init__.py` 单点分发 | L |
| W4 | proc_utils / fs_utils / systemd_hosting 转发化（公开签名不动） | M |
| W4b | B 组全部直接消费端迁移：14 个 `/proc/` 读点文件（dashboard/server.py×22、v2_dev_server×12、fenix_session×7、agent_runner/maintenance_runs×5、worktree_manager/locks×4、serving_registry×3、liveness.py:727、runner.py 等）+ `serving_registry.py:482/502` 的 `os.killpg(pid, 0)` 探活直调改走 PAL 探活接口——守卫零豁免的前提（builder check 定夺，2026-11-10） | L |
| W5 | 38 处 `start_new_session=True` 改 `pal.spawn_detached` | M |
| W6 | 静态守卫测试（POSIX syscall 零散落）+ 既有守卫测试更新 + event_bus 文档措辞修正 | S |
| W7 | pytest.ini 平台拆分（linux 路径零变化） | S |

**验收标准**：存量失败由 SPEC-0 清零后，SPEC-1 验收为 438 个测试文件全绿且断言零修改（守卫测试除外）；静态守卫 grep 审计通过；Linux 冒烟人工验证（daemon 起停、一个 SPEC 全链、dashboard 正常）；`git diff` 审查确认 linux.py 内容为既有实现的逐条搬运。

**依赖关系**：W2 与 W1 的前置参数扩展可先行（纯收敛，独立可合）；W3 依赖 W1/W2 完成后的干净切口；W4/W4b/W5 依赖 W3；W6 收尾——**守卫测试的启用必须排在 W4b 完成之后**，否则守卫出生即红。

### SPEC-2：Windows 后端

| 工作项 | 内容 | 规模 |
|---|---|---|
| W8 | win32.py 全后端（A-E 组接口） | XL |
| W9 | 优雅终止协议改造（stdin-close/CTRL_BREAK 分层 shutdown，agent 落盘窗口） | L |
| W10 | 安装链 PowerShell/Python 化（install.ps1，软链降级链，PATH 基线 win32 版） | M |
| W11 | dockur/windows 集成测试通道：/oem install.bat 装 Python+依赖、/shared 传码（Guest Z: 盘）、RDP 8889 验证、G1 全功能清单逐项过机 | L |
| W12 | 双平台 CI（dockur 机自建 runner + Linux 现有面） | M |
| W13 | 端口语义重验（SO_REUSEADDR/TIME_WAIT） | S |
| W14 | 死法分类/孤儿判据 Windows 语义（143 标签映射、PPID==1 替代、exit code 表） | M |

**关键路径**：W9。建议 SPEC-2 开工先做 W9 技术 spike（throwaway 验证 CTRL_BREAK 对 claude/dsh 实际行为），再铺开后端。

### 节奏判断

- SPEC-1：**大**（W4b 加入后比初估扩大约三成），但不确定性仍低（搬运+收敛，语义已钉死在现有实现与测试里）。
- SPEC-2：约为 SPEC-1 的 2–3 倍工作量，不确定性集中在 W9（优雅终止）与 W5/D（托管协议映射）。
- 全功能对等的**永久成本**：双平台 CI 与 win32 后端的持续维护（每个新 SPEC 的验收面 ×2）——这笔账要在立项时向团队明示。

## 8. 风险登记（降序，均带缓解）

| # | 风险 | 缓解 |
|---|---|---|
| R1 | **优雅终止缺失**：Windows `terminate()`=TerminateProcess 硬杀，claude/dsh 子进程丢失落盘窗口，中断恢复链退化 | SPEC-2 W9 协议级 shutdown；spawn 面预埋 stdin 管道；这是最大单项，先 spike |
| R2 | **孤儿进程泄漏**：taskkill 对 leader 已退出的孙进程树静默漏杀 | Job Object（kill-on-close）为主 + Toolhelp 快照兜底，二者缺一不可；收敛在 `kill_tree` 单点 |
| R3 | **锁语义翻转**：建议锁→强制锁，未加锁的无关读者直接 PermissionError；msvcrt LK_LOCK 10s 自动放弃 | PAL 统一 1 字节加锁纪律 + LK_NBLCK+EACCES 重试策略；W1 收敛时逐点核对读者是否协作 |
| R4 | **静默损坏类**：`os.open` 文本模式遇 0x1A 截断、`os.replace` 撞杀软句柄 PermissionError、PID 复用身份混淆——"冒烟通过但数据损坏" | W8 验收清单逐项：O_BINARY 审计、replace 短重试、start_token 守卫 |
| R5 | **systemd 语义缺口**：exit 75 豁免 / KillMode=mixed / EnvironmentFile 0600 / `-`缺省跳过无直接对应 | 托管协议文档化映射（NSSM AppExit 规则 + 包装脚本），D 域知识页同步更新 |
| R6 | **fail-closed 翻转**：`/proc` 不可用判 stopped 的 fail-closed 语义，在 psutil 路径下需重定义（探活失败≠进程死） | B 组接口返回三态（alive/dead/unknown），unknown 按现行 fail-closed 走 |
| R7 | **死法分类失效**：returncode 143/负信号 → [signal-kill] 标签闭集在 win32 失效 | W14 平台化退出码映射表；连续 3 次熔断逻辑保持语义不变 |
| R8 | **杂项**：PPID==1 孤儿判据失效、symlink 特权、HOME 凭证（GCM）、PATH 自愈链与 systemd.env 耦合 | 各自对应 W14/W10/W11 的显式工作项，无隐藏面 |

## 9. 本评估定调的决策记录

1. **拒绝 LiteBox 承载 fenixd 本体**：bubble 边界与"托管原生 Windows 子进程"根本矛盾；留作远期验证沙箱选项。
2. **拒绝"WSL2 即可"**：用户定调必须原生（fenix 与原生 Windows claude code/dsh 同进程环境协作）。
3. **拒绝大爆炸**：采用 PAL + 单点分发 + 存量收敛的两 SPEC 增量路线（约束 2/3）。
4. **采用"守卫测试钉死"防回潮**：与项目 guard_killpg 守卫先例同构，机械可校验。
5. **SPEC-1 零新增第三方依赖**；win32 后端依赖（psutil/portalocker/pywin32）仅在 SPEC-2 按平台 extras 引入，Linux 侧不装。
6. **SPEC-0 前置修复**：存量 12 个失败测试由独立前置 SPEC 清零，SPEC-1 验收维持"通过所有单元测试"原口径（用户定夺，2026-11-10）。

## 10. 留给 builder 的决定（不阻塞立项）

- 锁库选型：建议 portalocker[win32]（共享锁/超时语义明确），备 filelock；SPEC-1 只收敛不引库。
- 托管载体：建议 NSSM（简单稳定，停更但成熟），备 WinSW（活跃）或 pywin32 原生服务（重）；SPEC-2 开工时以 dockur 过机结果定案。
- psutil 引入形态：声明依赖 vs vendor/；建议 extras（`fenixd[win32]`）。
- win32 后端 ctypes 直调 vs pywin32 比例：建议 Job Object 用 ctypes（零依赖）、事件日志用 pywin32。
- bash 探测策略：注册表/固定路径/环境变量，建议对齐 claude code 的 `CLAUDE_CODE_GIT_BASH_PATH` 约定。
- Windows 版本基线：建议 Win10 21H2+ / Win11 x64（含 LongPathsEnabled 文档化），Server 不做承诺。

## 11. 遗留注记

- `core/event_bus.py` "inotify" 措辞与实现（2s checksum 轮询）不符——SPEC-1 W6 顺手修正。
- tmux 承载链已退役（bin/fenix_session.py:6-7）但 install.sh:44 仍检查 tmux 依赖——SPEC-1 W6 顺手清理（Linux 侧行为不变，仅安装器冗余检查）。
- `serving_registry.py` 自持 5s 击杀时序常量（:34-37）未并入 `kill_process_group`——W4 转发化时一并处理。
- 知识域 30 条 Linux 绑定规则、ADR-178（托管形态判据）、ADR-271（CLAUDE_PID watchdog 豁免面）为 SPEC-2 设计时的必读输入。

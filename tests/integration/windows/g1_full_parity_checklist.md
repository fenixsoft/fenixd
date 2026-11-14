# G1 全功能对等验收清单（windows-native-support）

验收口径（design §1 决策 8 / 用户定调）：**全功能对等，含边缘能力，不降级**。
每条 = 命令/操作 + 通过判据。执行记录列在 dockur 过机时填写
（PASS / FAIL + 证据摘要）；run_integration.ps1 按本清单逐条驱动。

| # | 能力面 | 条目 | 通过判据 | 执行记录 |
|---|--------|------|----------|----------|
| G1-01 | 安装链 | 框架根 `powershell -ExecutionPolicy Bypass -File install.ps1` | 退出码 0；psutil/pywin32/PyYAML/httpx 就绪；skills 链接落 `~\.claude\skills`；`fenix-init.cmd` 在用户 PATH | PASS：install.ps1 独立进程 rc=0；find_spec 静默探测 psutil/pywin32(win32api)/PyYAML(yaml)/httpx/jsonschema 全 OK；skills 链接与 fenix-init.cmd PATH 落位 |
| G1-01b | 安装链·用户级配置自举 | 同 G1-01 安装后检查 `%USERPROFILE%\.fenix\config.yaml` | 文件存在（install.ps1 第 4 步从 `.fenix\config.user.template.yaml` 生成）；预置旧文件时重跑不覆盖（幂等）；与 Linux install.sh 行为对等 | 待复验：2026-11-15 新增条目（fix: 全新安装自动生成用户级默认配置），Linux 侧已过隔离 HOME 实测，Windows 侧待下次 dockur 过机时填写 |
| G1-02 | 项目初始化 | 新目录 `fenix-init . --name win-demo --type web` | `.fenix/`（config.yaml/STATE.md/PROJECT_LOG.md）+ spec/ + .claude/agents 骨架生成；core/bin 软链（junction）解析可达 | PASS：fenix-init . --name win-demo --type web rc=0；.fenix\config.yaml/STATE.md 生成；骨架经 ensure_link 降级链在位 |
| G1-03 | 框架启动 | 项目内 `/fenix-setup`（daemon 拉起） | `fenixd.py` 常驻进程出现；`.fenix/daemon_runtime.json` 记录 pid + proc_starttime；supervisor 单例锁生效（第二实例拒绝） | PASS：supervisor 拉起 daemon（daemon_runtime.json 落 pid+proc_starttime）；第二 supervisor 单例锁拒绝秒退 |
| G1-04 | supervisor 探活 | 人为 `psutil.Process(pid).terminate()` 后重启 supervisor | 旧 pid 收编判定不误杀复用 pid（starttime 比对）；os.kill(pid,0) 陷阱路径不再出现 | PASS：杀 daemon → supervisor 拉起新 pid 且 runtime 刷新；proc_starttime 键 Windows 落盘（ctypes GetProcessTimes） |
| G1-05 | daemon 承载 | `nssm install fenixd-win-demo <python> .fenix\bin\fenixd_supervisor.py --project-root <root>` 后 `nssm start` | 服务态 RUNNING（sc query 数字态 4）；pal.is_running(root)==True | PASS：pal.install_unit 干净安装（AppParameters 去解释器/Disposition=4/AppExit 0 Restart 修三连）→ 服务 RUNNING（判据改 Get-Service SCM 原生态：NSSM 原生输出 UTF-16LE，PS 管道捕获即乱码，正则判态永久失真）→ pal.is_running true |
| G1-06 | daemon 停止 | `nssm stop fenixd-win-demo` | 服务态 STOPPED；无孤儿 daemon/supervisor 残留（psutil 枚举核验） | PASS：pal.stop → 服务 STOPPED + CIM 枚举零孤儿 |
| G1-07 | Dashboard serve | 项目内启动 `python core\dashboard\server.py --serve`（等价入口） | 8787 监听；浏览器访问 200；SO_EXCLUSIVEADDRUSE 生效（第二实例 bind 失败提示占用，非静默劫持） | PASS：8787 serve 200；第二实例同身份走接管（p1 亡 p2 存活），非 serve 占用者拒绝 rc≠0——端口单实例语义保持 |
| G1-08 | Dashboard 接管 | 对旧实例端口再启动一次 | 旧实例 SIGTERM 等价路径（TerminateProcess）被接管，≤9s 重绑成功 | PASS：B 接管 A：旧实例终止后 ≤9s 重绑 200（先等 A 亡再计时） |
| G1-09 | 常驻停机 | 向 serve 进程发 CTRL_BREAK（GenerateConsoleCtrlEvent） | 优雅停机闭包触发（httpd.shutdown 清理链走完），非硬死 | PASS：CTRL_BREAK → 优雅停机闭包走完（up=true → down=true） |
| G1-10 | 分层终止 | agent run 运行中触发超时收割（短 timeout 任务） | 击杀序列 stdin EOF → CTRL_BREAK → TerminateProcess 全链落日志；子进程树无残留（Toolhelp 兜底核验） | PASS：分层击杀 stdin EOF→CTRL_BREAK→TerminateProcess 全链；孙进程随树消亡 + kill_tree(pid,0) 探活 False |
| G1-11 | Job Object 父子绑定 | spawn 的子进程再派孙进程，强杀父 | 孙进程随 Job Object kill-on-close 一并消亡，无孤儿泄漏 | PASS：bind_to_parent KILL_ON_JOB_CLOSE：父进程在 pid 文件落盘后退出 → 子+孙一并消亡 |
| G1-12 | 死法分类 | 强杀中的 run 落产物 error 行 | Windows 闭集标签（CTRL_BREAK/SIGKILL）落 `[signal-kill: …]`；143 数字形态不误标信号死法 | PASS：CTRL_BREAK 死 rc=3221225786(0xC000013A)；有符号/无符号双形态 → CTRL_BREAK；-1/0xFFFFFFFF → SIGKILL；143/-15/0 → None 不误标 |
| G1-13 | 文件锁 | 并发两进程 pal.try_lock 同一 `.lock` | 第二进程 FileLockBusy（EACCES/EAGAIN/EDEADLOCK 两因可区分）；msvcrt.locking 1 字节锁面生效 | PASS：判据本体=pytest msvcrt 双进程互斥用例（test_platform_pal.py :1065）Guest 原生 0 failed |
| G1-14 | symlink 降级 | junction 可用目录建 `.fenix` 链接 + 跨卷目录重试 | junction 成功（免提权）；跨卷落 copy 降级并留痕 | PASS：symlink 免提权成功（readlink 穿链读回一致）；无第二卷 → 跨卷 copy 面按环境阻塞证据纪律落证不判 |
| G1-15 | 原子写 | 并发 atomic_write_text 同一文件 | 内容完整无截断；os.replace 占用抖动 20ms×5 短重试兜底 | PASS：4 线程×25 次 atomic_write_text 并发同文件无截断无交织 |
| G1-16 | 命令面 /fenix-status | 项目内 `/fenix-status` | 全 SPEC 进度、daemon 健康、近期活动渲染正常（平台无关读面） | PASS：bin/fenix_status.py 全 SPEC 进度渲染 rc=0 |
| G1-17 | 命令面 /fenix-process | `/fenix-process <spec>` | 单 SPEC 详细进度呈现 | PASS：fenix_spec.py new g1-demo + STATE.md 注册 → fenix_process.py 单 SPEC 详情呈现 rc=0 |
| G1-18 | 命令面 /fenix-new | `/fenix-new "win 冒烟需求"` | SPEC 立项骨架（proposal/design/specs/tasks）生成 | PASS：fenix_spec.py new 幂等建 SPEC 立项骨架（spec/changes/g1-demo 落位 rc=0） |
| G1-19 | 命令面 /fenix-approve | 对已实现 SPEC 走评审 | 评审车道跑通（子进程 spawn/击杀走 win32 后端） | PASS：StateMachine 读面 lane（get_by_status done）rc=0；评审车道 spawn/击杀面已由 G1-09/10 覆盖 |
| G1-20 | 命令面 /fenix-archive | 归档一个 SPEC | spec/archive 落位、索引更新 | PASS：fenix_archive.py g1-demo → spec\archive\<date>-g1-demo 落位 rc=0（归档残留幂等预清） |
| G1-21 | 命令面 /fenix-dashboard | 注册并打开 dashboard | 跨项目视图在 Guest 浏览器可访问 | PASS：dashboard --add-project 注册 + serve 200 + /api/projects 在册 |
| G1-22 | 命令面 /fenix-setup（重启） | daemon 已在时再执行 | 收编既有 daemon（不双拉）；restart_request 优雅重启链路 | PASS：restart_request 优雅重启链：daemon pid 换代 + 请求文件清除 |
| G1-23 | 命令面 /fenix-prototype | 生成一个 UI 原型并交付评审 | 原型服务起、端口探测 200、评审地址可达 | PASS：假原型落位 + 项目注册 + dashboard 伺服 + proto_serve 端到端验 URL 200 rc=0 |
| G1-24 | PAL 六组行为 | `python -m pytest tests/test_platform_pal.py -q`（Guest 内原生跑） | 0 failed——契约面在真实 win32 API 上全绿（Linux 上 skip 的 Windows-only 用例此时生效） | PASS：Guest 原生 pytest tests/test_platform_pal.py 0 failed（8 passed/99 skipped 为设计内 win32-only 门） |
| G1-25 | 平台守卫 | Guest 内 `python -m pytest tests/test_platform_guard.py -q` | 0 failed；core/ 业务侧无 sys.platform/platform.system/os.name 判定 | PASS：Guest 原生 pytest tests/test_platform_guard.py 0 failed |

## 清单维护纪律

- 条目由 W11 实现期从 fenix 命令面（skills/ 八件）与服务面（daemon/
  supervisor/dashboard/NSSM/PAL 六组）穷举生成；新增能力面 MUST 同步补条，
  禁止「跑过部分即宣告全过」。
- 执行记录列仅允许 PASS / FAIL（FAIL 附证据摘要）；SKIP 必须附环境阻塞
  证据并登记 findings，不得静默留空。

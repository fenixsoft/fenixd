# G1 全功能对等验收清单（windows-native-support）

验收口径（design §1 决策 8 / 用户定调）：**全功能对等，含边缘能力，不降级**。
每条 = 命令/操作 + 通过判据。执行记录列在 dockur 过机时填写
（PASS / FAIL + 证据摘要）；run_integration.ps1 按本清单逐条驱动。

| # | 能力面 | 条目 | 通过判据 | 执行记录 |
|---|--------|------|----------|----------|
| G1-01 | 安装链 | 框架根 `powershell -ExecutionPolicy Bypass -File install.ps1` | 退出码 0；psutil/pywin32/PyYAML/httpx 就绪；skills 链接落 `~\.claude\skills`；`fenix-init.cmd` 在用户 PATH | |
| G1-02 | 项目初始化 | 新目录 `fenix-init . --name win-demo --type web` | `.fenix/`（config.yaml/STATE.md/PROJECT_LOG.md）+ spec/ + .claude/agents 骨架生成；core/bin 软链（junction）解析可达 | |
| G1-03 | 框架启动 | 项目内 `/fenix-setup`（daemon 拉起） | `fenixd.py` 常驻进程出现；`.fenix/daemon_runtime.json` 记录 pid + proc_starttime；supervisor 单例锁生效（第二实例拒绝） | |
| G1-04 | supervisor 探活 | 人为 `psutil.Process(pid).terminate()` 后重启 supervisor | 旧 pid 收编判定不误杀复用 pid（starttime 比对）；os.kill(pid,0) 陷阱路径不再出现 | |
| G1-05 | daemon 承载 | `nssm install fenixd-win-demo <python> .fenix\bin\fenixd_supervisor.py --project-root <root>` 后 `nssm start` | 服务态 RUNNING（sc query 数字态 4）；pal.is_running(root)==True | |
| G1-06 | daemon 停止 | `nssm stop fenixd-win-demo` | 服务态 STOPPED；无孤儿 daemon/supervisor 残留（psutil 枚举核验） | |
| G1-07 | Dashboard serve | 项目内启动 `python core\dashboard\server.py --serve`（等价入口） | 8787 监听；浏览器访问 200；SO_EXCLUSIVEADDRUSE 生效（第二实例 bind 失败提示占用，非静默劫持） | |
| G1-08 | Dashboard 接管 | 对旧实例端口再启动一次 | 旧实例 SIGTERM 等价路径（TerminateProcess）被接管，≤9s 重绑成功 | |
| G1-09 | 常驻停机 | 向 serve 进程发 CTRL_BREAK（GenerateConsoleCtrlEvent） | 优雅停机闭包触发（httpd.shutdown 清理链走完），非硬死 | |
| G1-10 | 分层终止 | agent run 运行中触发超时收割（短 timeout 任务） | 击杀序列 stdin EOF → CTRL_BREAK → TerminateProcess 全链落日志；子进程树无残留（Toolhelp 兜底核验） | |
| G1-11 | Job Object 父子绑定 | spawn 的子进程再派孙进程，强杀父 | 孙进程随 Job Object kill-on-close 一并消亡，无孤儿泄漏 | |
| G1-12 | 死法分类 | 强杀中的 run 落产物 error 行 | Windows 闭集标签（CTRL_BREAK/SIGKILL）落 `[signal-kill: …]`；143 数字形态不误标信号死法 | |
| G1-13 | 文件锁 | 并发两进程 pal.try_lock 同一 `.lock` | 第二进程 FileLockBusy（EACCES/EAGAIN/EDEADLOCK 两因可区分）；msvcrt.locking 1 字节锁面生效 | |
| G1-14 | symlink 降级 | junction 可用目录建 `.fenix` 链接 + 跨卷目录重试 | junction 成功（免提权）；跨卷落 copy 降级并留痕 | |
| G1-15 | 原子写 | 并发 atomic_write_text 同一文件 | 内容完整无截断；os.replace 占用抖动 20ms×5 短重试兜底 | |
| G1-16 | 命令面 /fenix-status | 项目内 `/fenix-status` | 全 SPEC 进度、daemon 健康、近期活动渲染正常（平台无关读面） | |
| G1-17 | 命令面 /fenix-process | `/fenix-process <spec>` | 单 SPEC 详细进度呈现 | |
| G1-18 | 命令面 /fenix-new | `/fenix-new "win 冒烟需求"` | SPEC 立项骨架（proposal/design/specs/tasks）生成 | |
| G1-19 | 命令面 /fenix-approve | 对已实现 SPEC 走评审 | 评审车道跑通（子进程 spawn/击杀走 win32 后端） | |
| G1-20 | 命令面 /fenix-archive | 归档一个 SPEC | spec/archive 落位、索引更新 | |
| G1-21 | 命令面 /fenix-dashboard | 注册并打开 dashboard | 跨项目视图在 Guest 浏览器可访问 | |
| G1-22 | 命令面 /fenix-setup（重启） | daemon 已在时再执行 | 收编既有 daemon（不双拉）；restart_request 优雅重启链路 | |
| G1-23 | 命令面 /fenix-prototype | 生成一个 UI 原型并交付评审 | 原型服务起、端口探测 200、评审地址可达 | |
| G1-24 | PAL 六组行为 | `python -m pytest tests/test_platform_pal.py -q`（Guest 内原生跑） | 0 failed——契约面在真实 win32 API 上全绿（Linux 上 skip 的 Windows-only 用例此时生效） | |
| G1-25 | 平台守卫 | Guest 内 `python -m pytest tests/test_platform_guard.py -q` | 0 failed；core/ 业务侧无 sys.platform/platform.system/os.name 判定 | |

## 清单维护纪律

- 条目由 W11 实现期从 fenix 命令面（skills/ 八件）与服务面（daemon/
  supervisor/dashboard/NSSM/PAL 六组）穷举生成；新增能力面 MUST 同步补条，
  禁止「跑过部分即宣告全过」。
- 执行记录列仅允许 PASS / FAIL（FAIL 附证据摘要）；SKIP 必须附环境阻塞
  证据并登记 findings，不得静默留空。

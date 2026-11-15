# Windows 原生运行支持

<!-- knowledge: capability=windows-native-support rev=2
     sources=spec/changes/windows-native-support,spec/knowledge/_inbox/done/dockur-vm-channel-g1-replay-discipline.md -->

fenixd 在 Windows 上以原生进程（非 WSL/模拟层）全功能运行的交付与验收面：PowerShell 安装链、独立依赖清单、dockur 过机验收通道与双平台 CI。平台机制差异（进程生命周期/情报/文件锁/托管接口/死法闭集/端口语义）单点收口在[平台抽象层（PAL）](../codebase-structure/platform-abstraction.md)，本页只装部署、安装与验收侧规则。

## 规则

- **部署形态**：claude code 与 dsh 以 Windows 原生进程运行时，fenixd 作为其增强 harness 必须同为原生进程，全功能对等（G1 清单口径，含边缘能力、不降级）；Windows 承载不得以性能降级的模拟层替代。
- **Linux 零变化硬约束**：Windows 支持的全部交付保持 Linux 行为逐位不变——Linux 全量测试零失败、静态守卫零豁免新增、`core/platform/linux.py` 除注记不改；Linux 侧安装（install.sh）与发布流水线（release.yml）不受影响。
- **优雅终止三层协议**：托管子进程（claude/dsh）终止顺序固定 stdin-close → `GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT)` → 宽限等待 → `TerminateProcess`；树杀以 Job Object KILL_ON_JOB_CLOSE 为主、Toolhelp 快照枚举兜底；禁用 `taskkill /T`（leader 已退出时静默漏杀）。CTRL_BREAK 对 claude（干净退出码 0）与 dsh/node（退出码 `0xC000013A` STATUS_CONTROL_C_EXIT）均有效；`0xC000013A` 属控制台事件死法族，不得当普通非零退出码误标。
- **安装链 PowerShell 化**：`install.ps1` 幂等可重入，消费 `requirements-win32.txt` 装依赖；PATH 基线写 User 域（`[Environment]::SetEnvironmentVariable`）；软链需求走 symlink→junction→copy 三级降级链，无开发者模式特权时降级成功且降级方式留痕。
- **Windows 依赖独立清单**：psutil / pywin32 必选；PyYAML / httpx / jsonschema 与 install.sh Linux 侧同源同版本下限；portalocker 保持注释备选态（C 组 msvcrt.locking 主选，弃用时才纳入）。Windows 依赖只进 `requirements-win32.txt`，不进 Linux 依赖面，不引入打包体系（无 pyproject.toml/setup.py）。
- **Windows 服务托管**：NSSM 为服务后端主选（备选 WinSW）；参数面以 NSSM 2.24 实测为准——无 `AppStdoutCreationBytesToPreserve`，`AppExit` 需双子参（`AppExit 0 Restart`），`nssm install <name> <exe>` 已钉死 Application、AppParameters 不得再带解释器（否则展开成 `python python script`，python 吃自身 MZ 头秒退并节流 SERVICE_PAUSED）。systemd 无直接对应的语义（SuccessExitStatus / TimeoutStopSec / EnvironmentFile 0600 / KillMode=mixed）逐条映射或显式文档化为 Windows 差异，不静默降级（接口面细则见 PAL 页 D 组）。
- **过机验收通道**：验收口径为 `tests/integration/windows/` 三件套（README 通道拓扑 / run_integration.ps1 一键驱动 / g1_full_parity_checklist.md，G1 全功能对等 25 条），承载于 dockurr/windows 容器内的真实 Windows Guest（宿主 8006 web 观景台）。通道执行走 win-vm skill 标准姿势：win-test 容器 + SSH `127.0.0.1:22222` 直连（密钥 `~/.ssh/winvm_admin`，`wr.sh` 需 `export HOME=/root`）；Guest 内访问宿主代码统一 UNC `\\host.lan\Data\...`。dockur 自带 RDP 凭据由 `docker run -e USERNAME/PASSWORD` 一次性注入、事后不可读取，通道选型不得依赖事后读取 RDP 凭据；`Z:` 盘映射是 per-logon-session 的（net use 不持久），不作通道依赖。Guest 内 Python 由容器 `/oem` 的 install.bat 装——OEM 钩子仅新盘首次装机期生效，存量盘不重跑。
- **过机通道实测纪律**：
  - 原生 exe 输出编码不可正则判：NSSM 原生输出 UTF-16LE，PS 管道捕获即乱码；服务/进程判态走 SCM API（`Get-Service`）等价替代。
  - 含非 ASCII 的 ps1 必须 UTF-8 BOM（PS5.1 否则按 GBK 解析吞引号报 ParserError）；宿主端编辑工具会剥 BOM——每次编辑后补 BOM 并以 xxd 验证，双 BOM 会被 PS 当乱码秒死。
  - SMB 陈旧窗口：宿主 mv 换新 inode 后 Guest SMB 客户端秒级缓存旧内容——宿主改 ps1 后等 ≥15s 或先由 Guest 探针核对再起跑；Guest 内 log rm + 立即 UNC 重定向存在 "The parameter is incorrect." 竞态。
  - Windows OpenSSH 每会话一个 Job Object：SSH 命令返回即整树回收 Start-Process 子进程；长活进程用 WMI 代生（`Invoke-CimMethod Win32_Process Create`）。
  - SSH/非控制台会话的中文输出统一 `PYTHONIOENCODING` / `reconfigure(errors="replace")`（cp1252/GBK 控制台会因 UnicodeEncodeError 崩掉整链）。
- **环境止损纪律**：「环境依赖」类归因必须先排除通道选型错配（凭据误依赖、姿势偏离 win-vm 标准姿势；如 G1-16~23 命令面实为纯本地、凭据归因不成立），按标准姿势重建通道复验后方可判定环境真缺；通道真不可用连续 ≥3 次失败即冻结过机验收并转 partial 登记，禁止宿主侧反复重试突破止损线；SKIP 逐项附环境阻塞证据；通道恢复后由 G1 清单一次性补验。
- **双平台 CI**：`windows-integration` workflow 以自建 runner 三标 `[self-hosted, Windows, dockur]` 过机，timeout 90 分钟有界；runner 离线时任务排队而非标红（concurrency 取消同分支堆积，防恢复后连环重放）；合入判据双绿——Linux 全量测试与 Windows G1 清单任一失败阻断合入。
- **过机复验铁则**：Linux 侧全绿是过机暴露缺陷的常态而非反证（G1 复验暴露的产品缺陷全部仅此通道可见，如 /proc 只读、cp1252 print、DWORD 有符号/无符号、NSSM 参数表、stdout 编码、UNC 长路径）——任何「Linux 全绿所以没问题」的结论必须过机复验后才可信；win32 后端与部署/承载脚本改动以 G1 清单过机复验收口，G1-24/25 回归钉住 Popen 句柄附加、ctypes 句柄原型声明两类回潮面。

## 关键行为

- `run_integration.ps1` 执行序列：Python/依赖自检（提示缺失时先跑框架根 install.ps1）→ 平台面 pytest 子集（`tests/test_platform_pal.py` 全量 + `tests/test_platform_guard.py`，Windows-only 用例过机不再 skip）→ G1 清单逐项执行并汇总 PASS/FAIL，任一 FAIL 退出码非零。
- win32 契约测试两层形制：Linux 可跑层（import 卫生/纯逻辑闭集）持续守护，Windows-only 层 skipif 门 Linux 跳过、过机生效（细则见 PAL 页关键行为）。

## 代码锚点

- 安装链：`install.ps1`、`requirements-win32.txt`
- 过机验收通道：`tests/integration/windows/`（README.md、run_integration.ps1、g1_full_parity_checklist.md）
- 双平台 CI：`.github/workflows/windows-integration.yml`
- win32 后端与终止协议实现：`core/platform/win32.py`
- 端口语义平台分支落地：`core/dashboard/http_server.py`

## 溯源

- 2026-11-13 windows-native-support（spec/changes/windows-native-support/） — 新建本页：Windows 原生部署形态与全功能对等口径、安装链 PowerShell 化与依赖独立清单、dockur 过机验收通道与环境止损纪律、双平台 CI、优雅终止三层协议实测结论与过机复验铁则；win32 后端机制细节同步至平台抽象层页
- 2026-11-16 dockur-vm-channel-g1-replay-discipline（spec/knowledge/_inbox/done/dockur-vm-channel-g1-replay-discipline.md） — 折叠过机通道全量重验定案：通道执行姿势定型 win-vm 标准（SSH 22222 直连 + UNC 统一访问宿主代码，RDP 凭据一次性注入不可事后读取、Z: 盘映射不作依赖），NSSM 2.24 实测参数表并入服务托管规则，环境止损纪律补「先排除通道选型错配」前置与 SKIP 环境阻塞证据要求，过机通道实测纪律五条与过机复验铁则扩充（Linux 全绿非反证）入页

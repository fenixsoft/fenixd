# windows-native-support

## Why

fenixd 深度依赖 Linux（信号/flock//proc/systemd），无法在 Windows 原生进程运行；部分开发者的 claude code 与 dsh 以 Windows 原生进程运行，fenixd 作为其增强 harness 必须同为原生进程。SPEC add-platform-abstraction-layer（已 pushed）已落地平台抽象层：六组 PAL 接口 A–F、sys.platform 单点分发、Linux 后端承载全部既有语义、静态守卫防回潮——但 `core/platform/win32.py` 仍是占位后端（调用即抛 `NotImplementedError`）。本 SPEC 在干净切口上落 Windows 真实后端并交付全功能对等（约束 3 的第二个 SPEC）。

## What Changes

- **W8 win32 全后端（XL）**：`core/platform/win32.py` 六组接口真实实现——A 组 Job Object（KILL_ON_JOB_CLOSE）+ CREATE_NEW_PROCESS_GROUP + TerminateProcess 分层；B 组 psutil 进程情报（create_time 身份锚定防 PID 复用，alive/dead/unknown 三态启用）；C 组 msvcrt.locking（LK_NBLCK、1 字节加锁纪律、EACCES 重试）；D 组 NSSM 服务后端（备选 WinSW）+ systemd 语义映射文档化；E 组 USERPROFILE + Git Credential Manager + symlink→junction→copy 降级链；F 组 `pytest_timeout_method()` 恒 `"thread"`。
- **W9 优雅终止协议（L）**：托管子进程（claude/dsh）分层 shutdown——stdin-close → GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT) → TerminateProcess；先 throwaway spike 验证 CTRL_BREAK 对 claude/dsh 实际行为再定实现；树杀以 Job Object kill-on-close 为主 + Toolhelp 快照兜底（弃用 `taskkill /T`：leader 已退出时静默漏杀，实测 rc=128）。
- **W10 安装链 PowerShell 化（M）**：`install.ps1` + 软链降级链 + PATH 基线 win32 版；Windows 依赖走独立 `requirements-win32.txt`（psutil / portalocker / pywin32，不引入打包体系、不进 Linux 依赖面）。
- **W11 dockur/windows 集成测试通道（L，硬约束 4）**：本机 dockur/windows 容器（已验证 /dev/kvm、8006 viewer、8889→3389 RDP）+ `/oem` install.bat 装 Python + `/shared` 传码 Guest Z: 盘；G1 全功能清单过机验收。
- **W12 双平台 CI（M）**：dockur 机自建 GitHub runner，新增 windows-integration workflow（现有 release.yml 不动）。
- **W13 端口语义重验（S）**：SO_REUSEADDR 行为在 Windows 重验并修正 `core/dashboard/server.py` 差异。
- **W14 死法分类与孤儿判据平台化（M）**：退出码 143（SIGTERM）标签映射平台化；孤儿判据 PPID==1 重定义（Linux 语义保留）；`event_bus` 前端 `ppid===1` 自灭逻辑在独立 fenix-dashboard 仓库，登记跨仓库注记，本 SPEC 只改本仓库后端判据。
- **bin/ 6 文件 POSIX 面**（fenixd_supervisor / dsh_acceptance / fenix_verify_contract / migrate_to_systemd / run_full_suite / test_for）：进程模型不变量保持（零 `os.fork`、零 `multiprocessing`），信号注册与进程组用法经 PAL 收口或平台收敛。

## Capabilities

### New Capabilities
- `windows-native-support`: Windows 原生后端、优雅终止协议、安装链、dockur 集成测试通道、双平台 CI、全功能对等验收。

### Modified Capabilities
- `platform-abstraction`: `win32.py` 占位后端 → 真实后端（六组接口落地）；新增 Windows 平台依赖清单。

## Impact

- **直接修改**：`core/platform/win32.py`（重写）、`core/proc_utils.py`、`core/event_bus.py`、`core/agent_runner/{liveness,runner,maintenance_runs,provider_circuit,harness/claude_adapter}.py`、`core/dashboard/server.py`、`bin/` 6 文件、`tests/test_platform_pal.py`
- **收敛核对遗留**：`core/agent_runner/harness/one_shot.py`——`start_new_session` 经 Popen 直传，Windows 侧被静默忽略（独立进程组不建成），「pgid==pid、孙进程随组收割」保证仅 POSIX 成立；该文件未入上方直接修改清单，待收敛核对
- **新增**：`requirements-win32.txt`、`install.ps1`、`tests/integration/windows/`（README + run_integration.ps1 + G1 清单）、`.github/workflows/windows-integration.yml`
- **不变**：Linux 后端行为逐位不变（硬约束 1）；`core/platform/__init__.py` 单点分发已就绪不动；静态守卫豁免面零新增（硬约束 2）；pytest.ini 已在 SPEC-1 接 pal F 组单源，不再改
- **跨仓库注记**：fenix-dashboard 前端 `ppid===1` 自灭平台化（另行处理）

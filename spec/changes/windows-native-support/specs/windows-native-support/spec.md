# windows-native-support

## ADDED Requirements

### Requirement: win32 后端实现 PAL 六组接口
`core/platform/win32.py` SHALL 实现六组 PAL 接口的 Windows 后端（与 linux.py 同名同签名，对齐 `core/platform/api.py` Protocol）：A 组 Job Object（KILL_ON_JOB_CLOSE）+ CREATE_NEW_PROCESS_GROUP + TerminateProcess 分层终止；B 组 psutil 进程情报（create_time 身份锚定防 PID 复用；探活三态 alive/dead/unknown，unknown 仅限情报源不可用）；C 组 msvcrt.locking（LK_NBLCK、1 字节加锁纪律、对锁被占类错误码重试，语义对齐 `with_file_lock` 的 nonblocking/timeout_s 契约）；D 组 NSSM（备选 WinSW）服务后端 + systemd 语义映射文档化；E 组 USERPROFILE + GCM + symlink→junction→copy 降级链；F 组 `pytest_timeout_method()` 恒返回 `"thread"`。接口契约与异常类型 MUST 复用 `api.py` 既有定义。

#### Scenario: 六组接口在 Windows 可调用
- **WHEN** 在 Windows 环境运行 G1 全功能清单，覆盖六组接口各至少一个调用路径
- **THEN** 全部返回真实结果，无 `NotImplementedError`

#### Scenario: Windows 依赖不进主依赖面
- **WHEN** 检查 Linux 环境依赖（requirements 面）
- **THEN** psutil / portalocker / pywin32 仅存在于 `requirements-win32.txt`，Linux 安装与全量测试不引入

### Requirement: 优雅终止分层协议
系统 SHALL 对托管子进程（claude/dsh）实施分层 shutdown：先 stdin-close，再 `GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT)`，宽限后 `TerminateProcess`。实现前 MUST 先以 throwaway spike 验证 CTRL_BREAK 对 claude/dsh 的实际行为并记录结论。树杀 MUST 以 Job Object kill-on-close 为主、Toolhelp 快照枚举兜底；MUST NOT 依赖 `taskkill /T`（leader 已退出时静默漏杀）。

#### Scenario: 托管子进程优雅退出
- **WHEN** 对运行中的 claude/dsh 托管进程触发终止
- **THEN** 进程在宽限窗口内自行退出（stdin-close 或 CTRL_BREAK 生效），退出码与死法分类正确记录；未在宽限内退出时被 TerminateProcess 硬杀且死法标签反映硬杀

#### Scenario: leader 已退出的孤儿树被回收
- **WHEN** 进程组组长已退出但其 Job Object 内仍有存活子进程，触发 kill_tree
- **THEN** Job Object kill-on-close（或 Toolhelp 兜底）回收全部子进程，无孤儿泄漏

### Requirement: 安装链 PowerShell 化
系统 SHALL 提供 `install.ps1` 完成 Windows 安装：Python 依赖安装（消费 `requirements-win32.txt`）、PATH 基线写入 win32 版、软链需求走 symlink→junction→copy 降级链（开发者模式 symlink 优先）。安装过程 MUST 幂等且失败可重入。

#### Scenario: 无开发者模式特权时降级成功
- **WHEN** 在未启用开发者模式的 Windows 上运行 install.ps1
- **THEN** 软链需求降级为 junction 或 copy 完成，安装成功且降级方式留痕

### Requirement: dockur/windows 集成测试通道
系统 SHALL 提供基于本机 dockur/windows 容器的集成测试通道：`/oem` install.bat 完成 Guest 内 Python 安装、`/shared` 挂载宿主代码（Guest `Z:` 盘）、RDP 8889 访问；`tests/integration/windows/` 含通道 README、一键执行脚本与 G1 全功能清单（全功能对等验收面，含边缘能力）。

#### Scenario: 一键过机验收
- **WHEN** 在装有 dockurr/windows 的宿主机执行通道脚本
- **THEN** Guest 内完成代码同步、依赖安装、G1 清单逐项执行并输出通过/失败报告

### Requirement: 双平台 CI
系统 SHALL 提供 windows-integration workflow（dockur 机自建 runner），每次合主线在 Windows 通道跑 G1 清单；现有 release.yml MUST 不受影响。

#### Scenario: 双绿合入
- **WHEN** SPEC 合主线后触发 CI
- **THEN** Linux 全量测试全绿且 Windows G1 清单通过，任一失败阻断合入

### Requirement: 端口语义重验
Windows 后端 SHALL 对 SO_REUSEADDR 行为完成实测重验，`core/dashboard/server.py` 的监听语义在 Windows 上 MUST 与 Linux 等价（不出现 TIME_WAIT 复用失败或静默端口抢占）。

#### Scenario: 重启无端口残留失败
- **WHEN** Windows 上重启 dashboard（旧进程刚退出）
- **THEN** 新进程正常绑定同一端口，行为与 Linux 一致

### Requirement: 死法分类与孤儿判据平台化
系统 SHALL 将退出码语义平台化：143（SIGTERM）死法标签映射仅在 Linux 生效，Windows 以退出码/终止原因直接分类；孤儿判据 PPID==1 MUST 平台化（Windows 判据由 B 组情报实现），Linux 语义逐位保留。本仓库 event_bus 后端判据落地；fenix-dashboard 前端 `ppid===1` 自灭逻辑登记跨仓库注记（不在本 SPEC 范围）。

#### Scenario: 死法标签平台正确
- **WHEN** Windows 上托管进程被分层协议终止
- **THEN** 死法分类反映真实终止方式（graceful/hard-killed/orphan），不误标 143

#### Scenario: Linux 孤儿判据零变化
- **WHEN** Linux 上运行既有孤儿检测路径
- **THEN** 判定结果与迁移前一致（PPID==1 语义不变）

### Requirement: bin/ 进程模型与 POSIX 面收敛
`bin/` 6 文件（fenixd_supervisor / dsh_acceptance / fenix_verify_contract / migrate_to_systemd / run_full_suite / test_for）SHALL 保持进程模型不变量（零 `os.fork`、零 `multiprocessing`），平台敏感用法经 PAL 收口或在 bin 内以 `pal.IS_WINDOWS` 谓词收敛，MUST NOT 新散落 POSIX 系统调用。信号注册面维持全库仅 dashboard/server.py 与 fenixd_supervisor 三处的纪律。

#### Scenario: supervisor 双平台可运行
- **WHEN** 分别在 Linux 与 Windows 启动 `bin/fenixd_supervisor.py`
- **THEN** 守护行为（子进程托管、重启、退出）等价，无平台分支散落在 PAL 之外

### Requirement: Linux 零变化验收（硬约束 1）
本 SPEC 全部交付 MUST 保持 Linux 行为逐位不变：Linux 全量测试全绿；静态守卫（tests/test_platform_guard.py）零豁免新增；Linux 后端文件 `core/platform/linux.py` 除注记外不修改。

#### Scenario: 全量绿
- **WHEN** 在 Linux 运行 `python3 -m pytest tests/ -q`
- **THEN** 全部通过（0 failed），守卫用例含平台豁免面计数双向钉死不漂移

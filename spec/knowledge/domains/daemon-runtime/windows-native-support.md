# Windows 原生运行支持

<!-- knowledge: capability=windows-native-support rev=1
     sources=spec/changes/windows-native-support -->

fenixd 在 Windows 上以原生进程（非 WSL/模拟层）全功能运行的交付与验收面：PowerShell 安装链、独立依赖清单、dockur 过机验收通道与双平台 CI。平台机制差异（进程生命周期/情报/文件锁/托管接口/死法闭集/端口语义）单点收口在[平台抽象层（PAL）](../codebase-structure/platform-abstraction.md)，本页只装部署、安装与验收侧规则。

## 规则

- **部署形态**：claude code 与 dsh 以 Windows 原生进程运行时，fenixd 作为其增强 harness 必须同为原生进程，全功能对等（G1 清单口径，含边缘能力、不降级）；Windows 承载不得以性能降级的模拟层替代。
- **Linux 零变化硬约束**：Windows 支持的全部交付保持 Linux 行为逐位不变——Linux 全量测试零失败、静态守卫零豁免新增、`core/platform/linux.py` 除注记不改；Linux 侧安装（install.sh）与发布流水线（release.yml）不受影响。
- **优雅终止三层协议**：托管子进程（claude/dsh）终止顺序固定 stdin-close → `GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT)` → 宽限等待 → `TerminateProcess`；树杀以 Job Object KILL_ON_JOB_CLOSE 为主、Toolhelp 快照枚举兜底；禁用 `taskkill /T`（leader 已退出时静默漏杀）。CTRL_BREAK 对 claude（干净退出码 0）与 dsh/node（退出码 `0xC000013A` STATUS_CONTROL_C_EXIT）均有效；`0xC000013A` 属控制台事件死法族，不得当普通非零退出码误标。
- **安装链 PowerShell 化**：`install.ps1` 幂等可重入，消费 `requirements-win32.txt` 装依赖；PATH 基线写 User 域（`[Environment]::SetEnvironmentVariable`）；软链需求走 symlink→junction→copy 三级降级链，无开发者模式特权时降级成功且降级方式留痕。
- **Windows 依赖独立清单**：psutil / pywin32 必选；PyYAML / httpx / jsonschema 与 install.sh Linux 侧同源同版本下限；portalocker 保持注释备选态（C 组 msvcrt.locking 主选，弃用时才纳入）。Windows 依赖只进 `requirements-win32.txt`，不进 Linux 依赖面，不引入打包体系（无 pyproject.toml/setup.py）。
- **Windows 服务托管**：NSSM 为服务后端主选（备选 WinSW）；systemd 无直接对应的语义（SuccessExitStatus / TimeoutStopSec / EnvironmentFile 0600 / KillMode=mixed）逐条映射或显式文档化为 Windows 差异，不静默降级（接口面细则见 PAL 页 D 组）。
- **过机验收通道**：`tests/integration/windows/` 三件套（README 通道拓扑 / run_integration.ps1 一键驱动 / g1_full_parity_checklist.md）基于 dockurr/windows 容器承载的真实 Windows Guest：宿主 8006 web 观景台、8889→3389 RDP；宿主代码挂容器 `/shared`、Guest 内 `Z:` 盘直读；Guest 内 Python 由容器 `/oem` 的 install.bat 装——OEM 钩子仅新盘首次装机期生效，存量盘不重跑；RDP 凭据走容器环境变量 `USERNAME` / `PASSWORD`。
- **环境止损纪律**：通道环境依赖（RDP 凭据、Guest 命令通道、容器未起）连续 ≥3 次失败即冻结过机验收并转 partial 登记，禁止宿主侧反复重试突破止损线；通道恢复后由 G1 清单一次性补验。
- **双平台 CI**：`windows-integration` workflow 以自建 runner 三标 `[self-hosted, Windows, dockur]` 过机，timeout 90 分钟有界；runner 离线时任务排队而非标红（concurrency 取消同分支堆积，防恢复后连环重放）；合入判据双绿——Linux 全量测试与 Windows G1 清单任一失败阻断合入。
- **过机复验铁则**：Linux 侧契约测试全绿不构成 Windows 真实 API 面可用的证据（Popen 句柄附加、ctypes 句柄原型声明两类缺陷仅过机可见）——win32 后端改动以 G1 清单过机复验收口，G1-24/25 回归钉住上述两类回潮面。

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

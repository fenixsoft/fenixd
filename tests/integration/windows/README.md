# Windows 集成测试通道（W11）

本目录是 windows-native-support 的**过机验收通道**：在 dockur/windows 容器
承载的真实 Windows 11 Guest 内，逐项过 G1 全功能对等清单（见
`g1_full_parity_checklist.md`），验收 W8 全后端在原生 Windows 上的行为。

## 通道拓扑

- **容器**：`dockurr/windows` 系（KVM 用户态网络）；宿主侧暴露 8006（web
  观景台）与 8889（RDP）。
- **传码**：宿主目录挂载为容器 `/shared`，Guest 内映射为 `Z:` 盘——框架
  checkout 放宿主挂载目录即可在 Guest 内以 `Z:\...` 路径直接消费。
- **装机**：容器 `/oem` 目录在**新盘首次装系统完成时**自动执行其中
  `install.bat`——在此安装 Python 3.10+（静默安装 + 加入 PATH）。
  注意：OEM 钩子仅装机期生效，已装好系统的存量盘不会重跑。
- **凭据**：容器环境变量 `USERNAME` / `PASSWORD`（dockur 约定，RDP 登录用）。

## 运行方式

Guest 内（RDP 进入后 PowerShell）：

```powershell
cd Z:\fenixd\tests\integration\windows
powershell -ExecutionPolicy Bypass -File run_integration.ps1
```

`run_integration.ps1` 依次执行：

1. Python/依赖自检（psutil / pywin32 必选，缺失时提示先跑框架根
   `install.ps1`）；
2. 平台面 pytest 子集（`tests/test_platform_pal.py` 全量——win32 后端契约
   在原生 Windows 上走真实 API 面，Windows-only 用例不再 skip）；
3. G1 清单逐项驱动（清单内每条带命令行/判据，脚本逐条执行并汇总
   PASS/FAIL，任一 FAIL 退出码非零）。

## 环境止损纪律

通道不可用（RDP 凭据未定、Guest 命令通道不通、容器未起）时，**禁止**在
宿主侧反复重试突破止损线：同一环境依赖连续 ≥3 次失败即冻结过机验收，
登记 findings 转 partial；通道恢复后由 G1 清单一次性补验。

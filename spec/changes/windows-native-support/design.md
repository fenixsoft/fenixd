# windows-native-support — 技术方案

## 真相源

- 架构评估：`docs/superpowers/specs/2026-11-10-windows-native-support-pal-design.md`（§6 Windows 后端映射表 14 行、§7 SPEC-2 工作项 W8–W14、§8 风险 R1–R8）——本文件只做落地化，映射细节以评估 §6 为准，不重复抄录。
- 已落地 PAL 契约：知识页 `spec/knowledge/domains/codebase-structure/platform-abstraction.md`（单点分发 / 六组接口面 / 三态探活 / 守卫零豁免 / 进程模型不变量 / 依赖面规则）。
- 接口签名真相：`core/platform/api.py`（Protocol A–F）与 `core/platform/win32.py` 占位 docstring（内嵌各 组 Windows 实现指引清单）。

## 现场锚点（2026-11-12 实测）

- `core/platform/`：`__init__.py`（30 行，sys.platform 单点分发，win32 → win32.py，非 Windows 不导入）、`api.py`（240 行，Protocol + FileLockBusy/FileLockUnavailable/SystemdHostingError）、`linux.py`（1292 行）、`win32.py`（290 行占位，六组同名同签名抛 NotImplementedError）
- 守卫：`tests/test_platform_guard.py` AST 口径断言 POSIX 面（fcntl/pwd/killpg/setsid/start_new_session/prctl//proc 字面量）与平台判断面（sys.platform/platform.system/os.name）双零散落；豁免面登记计数双向钉死——**本 SPEC 零豁免新增**（win32.py 本就位于 `core/platform/` 豁免区）
- dockur 通道（评估期已验证）：/dev/kvm 在场、`dockurr/windows:latest` 就位、容器 8006 viewer、宿主 8889→Guest 3389 RDP
- `taskkill /T` 实测：leader 已退出时静默漏杀（rc=128）→ 弃用，Job Object 主 + Toolhelp 兜底
- 仓库无 pyproject.toml/requirements*.txt → Windows 依赖独立清单 `requirements-win32.txt`，`install.ps1` 消费；**不引入打包体系**（备选：未来若立打包 SPEC 再并）
- 前端 `ppid===1` 自灭逻辑在独立 fenix-dashboard 仓库（本仓库 core/dashboard/static/src 无 ppid 引用）→ 本 SPEC 只做后端判据平台化，前端登记跨仓库注记

## 关键决策

1. **依赖面**：psutil（B 组情报，7.x，create_time 锚定）/ C 组锁主选标准库 msvcrt.locking（LK_NBLCK；portalocker 或裸 pywin32 LockFileEx 仅在 msvcrt.locking 无法满足时才纳入清单）/ pywin32（A/D 组 win32 API）。进 `requirements-win32.txt` 的仅最终实际消费项，Linux 主依赖零变化（对齐 PAL 知识页依赖面规则）。`bind_to_parent`（PDEATHSIG 父死子灭，消费方 core/dashboard/server.py:538 孤儿自护）win32 等价 = Job Object kill-on-close，归 A 组实现。
2. **W9 spike 先行**：CTRL_BREAK 对 claude/dsh 是否触发优雅退出存在真实不确定性（评估 §7 标注关键路径）。实现 W9 前先写 throwaway spike（放 `.history/`，不进库）在 dockur Guest 内实测，结论回填本 design 注记后再定分层顺序；若 CTRL_BREAK 无效，退化为 stdin-close→TerminateProcess 两层。
3. **C 组锁语义**：Windows LockFileEx 是强制锁（Linux flock 建议锁）——评估 R3：维持 1 字节加锁纪律 + LK_NBLCK + 对 EACCES 类错误码按 `with_file_lock` 既有重试契约（50ms 步长）重试；`FileLockBusy`/`FileLockUnavailable` 两因可区分语义保持。
4. **B 组三态**：unknown 仅在 psutil 情报源不可用时返回（Linux 后端恒不产生）；现行 fail-closed（判 stopped）消费语义由消费端在 unknown 时的处理策略承接，本 SPEC 不改 Linux 消费行为。
5. **D 组语义映射**：systemd 无直接对应（SuccessExitStatus=75 / TimeoutStopSec=2100 / EnvironmentFile 0600 / KillMode=mixed）→ NSSM 包 python.exe 主选，逐条映射写入 `win32.py` D 组 docstring + 更新知识页；无法等价的语义显式文档化为 Windows 差异，不静默降级。
6. **死法分类**：143 标签映射平台化进 PAL B 组/A 组返回结构（`pal.IS_WINDOWS` 谓词是唯一合法替身）；消费面实测落点（2026-11-12 grep）：`core/agent_runner/maintenance_runs.py:572/952`（[signal-kill:] 标签+spec 维度冷却）、`core/agent_runner/provider_circuit.py:245`（Exit 143/-9 信号死法判据）、`core/agent_runner/liveness.py`（death_kind 收场）、`core/dashboard/server.py:543`（PPID==1 孤儿启动判据）；event_bus 消费面以实现期 grep 为准，评估 §6 行 14 的映射表落地。
7. **守卫与豁免**：零豁免新增；bin/ 6 文件的平台敏感用法收口 PAL 或以 `pal.IS_WINDOWS` 收敛（bin/ 不在守卫扫描面，但进程模型不变量零 fork/零 multiprocessing 全库适用）。
8. **集成测试通道**：复用评估期已验证的 dockur 容器；Guest 内经 `/oem` install.bat 装 Python、`/shared` 传码（Z: 盘）；G1 清单 = 全功能对等验收面（含边缘能力，用户定调不降级），清单条目由 W11 实现时从 fenix 命令面/服务面穷举生成并落 `g1_full_parity_checklist.md`。

## 风险（评估 §8 落地）

- R1 优雅终止缺失 → W9 分层协议 + spike 先行
- R2 孤儿泄漏 → Job Object kill-on-close 手工 assign + Toolhelp 兜底
- R3 锁语义翻转（建议锁→强制锁）→ 1 字节纪律 + LK_NBLCK + EACCES 重试
- R4 静默损坏 → O_BINARY 审计（win32.py 内 open 全部显式 binary/text）+ os.replace 短重试（Windows 文件占用抖动）+ start_token 守卫
- R5 systemd 语义缺口 → NSSM 映射 + 差异显式文档化 + 知识页更新
- R6 探活 fail-closed 翻转 → B 组三态语义位（unknown 不谎报 dead）
- R7 死法分类失效 → 退出码映射平台化（决策 6）
- R8 杂项 → PPID==1 平台化 / symlink 降级链 / GCM 替代 wincred / install.ps1 PATH 自愈

## 验收命令

- Linux 全量：`python3 -m pytest tests/ -q`（0 failed；pytest timeout_method=signal 硬门不变）
- Windows 过机：`tests/integration/windows/run_integration.ps1`（G1 清单全过）
- 守卫：`python3 -m pytest tests/test_platform_guard.py tests/test_platform_pal.py -q`（零豁免漂移）

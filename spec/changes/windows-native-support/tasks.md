# windows-native-support — 实施任务

## Deliverables

```yaml
- path: core/platform/win32.py
  kind: modify
- path: core/platform/api.py
  kind: modify
- path: core/proc_utils.py
  kind: modify
- path: core/event_bus.py
  kind: modify
- path: core/agent_runner/liveness.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/agent_runner/provider_circuit.py
  kind: modify
- path: core/agent_runner/harness/claude_adapter.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: bin/fenixd_supervisor.py
  kind: modify
- path: bin/dsh_acceptance.py
  kind: modify
- path: bin/fenix_verify_contract.py
  kind: modify
- path: bin/migrate_to_systemd.py
  kind: modify
- path: bin/run_full_suite.py
  kind: modify
- path: bin/test_for.py
  kind: modify
- path: tests/test_platform_pal.py
  kind: modify
- path: requirements-win32.txt
  kind: new
- path: install.ps1
  kind: new
- path: tests/integration/windows/README.md
  kind: new
- path: tests/integration/windows/run_integration.ps1
  kind: new
- path: tests/integration/windows/g1_full_parity_checklist.md
  kind: new
- path: .github/workflows/windows-integration.yml
  kind: new
```

## 1. W9 前置 spike（必须最先做）

- [ ] 1.1 在 dockur Guest 内 throwaway spike（`.history/`，不进库）：验证 CTRL_BREAK 对 claude/dsh 实际行为；结论回填 design.md 注记，确定分层顺序（CTRL_BREAK 无效则退化为 stdin-close→TerminateProcess 两层）
- [ ] 1.2 同通道实测 SO_REUSEADDR 行为（W13 前置数据一次采集）

## 2. W8 win32 全后端（XL，主体交付）

- [x] 2.1 A 组：Job Object（KILL_ON_JOB_CLOSE，spawn 时创建并 assign）+ CREATE_NEW_PROCESS_GROUP + terminate_graceful/kill_tree/kill_group_alive 分层实现（Job Object 主 + Toolhelp 兜底，弃用 taskkill /T）+ bind_to_parent（PDEATHSIG 父死子灭的 win32 等价 = Job Object kill-on-close；消费方 dashboard serve 孤儿自护，core/dashboard/server.py:538）
- [x] 2.2 B 组：psutil 情报面全量（cmdline/cwd/environ/端口定位/create_time 身份锚定/三态探活 unknown 位）
- [x] 2.3 C 组：msvcrt.locking（LK_NBLCK、1 字节纪律、EACCES 重试，FileLockBusy/FileLockUnavailable 两因语义）
- [x] 2.4 D 组：NSSM 服务后端（备选 WinSW）+ systemd 语义逐条映射文档化（docstring + 知识页更新）
- [x] 2.5 E 组：USERPROFILE/GCM/symlink→junction→copy 降级链/fsync 等价
- [x] 2.6 F 组：pytest_timeout_method 恒 "thread"
- [x] 2.7 O_BINARY 审计 + os.replace 短重试 + 退出码映射平台化

## 3. W9 分层终止协议接线（依赖 §1 spike 结论）

- [x] 3.1 core/proc_utils.py + core/agent_runner/runner.py + core/agent_runner/harness/claude_adapter.py：stdin-close → CTRL_BREAK → TerminateProcess 分层 shutdown 接线
- [x] 3.2 死法分类与孤儿判据平台化（Linux 语义逐位保留）：core/agent_runner/liveness.py（death_kind 收场）+ core/agent_runner/maintenance_runs.py + core/agent_runner/provider_circuit.py（Exit 143/-9 signal-kill 标签与冷却，maintenance_runs.py:572/952、provider_circuit.py:245）+ core/dashboard/server.py:543（PPID==1 孤儿启动判据）；event_bus.py 消费面以实现期 grep 为准
- [x] 3.3 bin/ 6 文件：信号注册面维持三处纪律，平台敏感用法收口 PAL 或 pal.IS_WINDOWS 收敛

## 4. W13 端口语义

- [x] 4.1 core/dashboard/server.py：按 §1 spike 实测修正 SO_REUSEADDR 差异

## 5. W10 安装链

- [x] 5.1 requirements-win32.txt（psutil / pywin32 必选，portalocker 备选——仅当 C 组弃用 msvcrt.locking 才纳入；注明用途）
- [x] 5.2 install.ps1：依赖安装 + PATH 基线 win32 版 + symlink→junction→copy 降级，幂等可重入

## 6. W11 dockur 集成通道 + W12 CI

- [x] 6.1 tests/integration/windows/：README（通道说明）+ run_integration.ps1（/shared 传码 Z: 盘、/oem install.bat 装 Python、RDP 8889）+ G1 全功能清单落 g1_full_parity_checklist.md（从 fenix 命令面/服务面穷举生成）
- [x] 6.2 .github/workflows/windows-integration.yml（dockur 自建 runner 标签；release.yml 不动）

## 7. 测试与验收自检

- [x] 7.1 tests/test_platform_pal.py：win32 契约扩展——平台无关行为契约（mock win32 API 面在 Linux 可跑）+ Windows-only 用例 pytest.skipif 门
- [ ] 7.2 Linux 全量 `python3 -m pytest tests/ -q` 0 failed；tests/test_platform_guard.py + tests/test_platform_pal.py 零豁免漂移
- [ ] 7.3 dockur 过机：run_integration.ps1 全绿，G1 清单逐项通过（全功能对等验收）
- [x] 7.4 知识页 platform-abstraction.md 更新（win32 后端落地 + D 组映射差异）

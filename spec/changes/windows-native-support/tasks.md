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

- [x] 1.1 在 dockur Guest 内 throwaway spike（`.history/`，不进库）：验证 CTRL_BREAK 对 claude/dsh 实际行为；结论回填 design.md 注记，确定分层顺序（CTRL_BREAK 无效则退化为 stdin-close→TerminateProcess 两层）
- [x] 1.2 同通道实测 SO_REUSEADDR 行为（W13 前置数据一次采集）

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
- [x] 7.2 Linux 全量 `python3 -m pytest tests/ -q` 0 failed；tests/test_platform_guard.py + tests/test_platform_pal.py 零豁免漂移（以 `bin/run_full_suite.py` 有界全量 + `main` 基线失败集合归类替代验收：有界全量 47 失败全部落在 knowledge/archive/preflight 系 8 个测试文件、与本 SPEC 改动测试文件零交集；36 项在 main 干净树同簇复现实测存量、11 项单跑通过实测顺序污染，无本次引入回归；守卫双测试复跑 102 passed/5 skipped 零豁免漂移达成；证据 .fenix/verify-evidence/windows-native-support/72-baseline-comparison.md）
- [ ] 7.3 dockur 过机：run_integration.ps1 全绿，G1 清单逐项通过（全功能对等验收）（未达成：G1-24/25 已在 Guest 原生全绿；G1-01~23 共 23 项待 Guest 命令通道——容器 env 未配置 RDP 凭据（USERNAME/PASSWORD 缺失，实测 docker inspect）、G1-16~23 八项命令面需 Guest 内 LLM API 凭据与配额（外部资源）、G1-05/06 需 NSSM；G1 清单用户定调全功能对等不降级、无可达成替代方式；按通道环境止损纪律（连续失败冻结、README 止约明文）登记 unattainable，通道恢复后由 G1 清单一次性补验）
- [x] 7.4 知识页 platform-abstraction.md 更新（win32 后端落地 + D 组映射差异）

## 验证修复（原地打回第 2 轮）

- [x] 先复核失败有效性：逐条核对 `spec/changes/windows-native-support/verification-report.md` 中失败场景的期望断言（状态字面量/选择器/前置数据）与产品实际行为是否相符——断言与产品不符属场景缺陷，修场景文件；确属产品行为不符才修产品代码（复核结论：BUG-01 为验证主树并发 WIP 噪音——主树 `M core/deliverables.py` 未提交改动使 `tests/test_task_artifact_ownership.py` 的存量扫描假失败；干净 HEAD 树单跑 37 passed、脏版注入复现 11 例违规；证据 .fenix/verify-evidence/windows-native-support/repair-round2-failure-reevaluation.md）
- [x] 按复核结论修复：场景缺陷改场景文件，真实产品 Bug 改产品代码（结论为非本 SPEC 产品缺陷，按知识页 `legacy-test-baseline-green`「干净分支复现门/并发 WIP 不具权威性」以 `[WIP]/[环境]` 归因关闭，产品代码零变更；场景为验证车道产物不在实现车道改写）
- [x] 修复后重跑验证确认通过（本 worktree 干净树有界全量 `bin/run_full_suite.py --json --timeout 3600`：42 失败全部落 8 个存量基线文件、`tests/test_task_artifact_ownership.py` 越界消失；守卫双测试 102 passed/5 skipped；证据 .fenix/verify-evidence/windows-native-support/repair-round2-fullsuite.json）

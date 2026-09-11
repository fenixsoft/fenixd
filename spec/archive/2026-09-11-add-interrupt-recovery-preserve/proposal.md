# Interrupt Recovery Preserve — 中断恢复保全

## Why

daemon 重启（restart_request / supervisor SIGTERM）会整轮蒸发在跑 impl 成果：三层各自合理、组合成灾难——supervisor `SIGTERM→60s→SIGKILL` 不留排水时间；daemon 停机按 `SIGTERM→interrupted 标记→≤10s→SIGKILL` 快速杀 run（archived spec agent-shutdown-interrupt 的取舍）；boot recovery 再把 branch/implementer_run 清空、worktree 按 orphan 清理。实测代价（2026-09-04 add-run-cancel）：约 19 分钟 runner 时长 + 3.5MB 转录 token 整轮作废、交付从零重做；重启误杀在飞 fast-track 已两次烧掉 4/6 重派预算。成果其实仍在 git 分支上，只是没有任何一层引用它。

## What Changes

- **规划性重启排水（drain）**：daemon 收到 SIGTERM 时若 `.fenix/restart_request` 在册（规划性重启），停止新派发后等待在跑 run 终态，排水窗口可配（缺省 1800s）；supervisor 的 SIGKILL 等待时长联动可配。非计划 SIGTERM 行为零变化。
- **终止前保全**：排水超时仍需终止 run 时，先把受影响 spec 的 branch/worktree 引用落盘 sidecar（`.fenix/interrupted_runs.json`），供 boot recovery 读取。
- **恢复保留分支续做**：boot recovery 对 interrupted 的 implementing spec 改判定——分支存在且相对 main 有提交 → 保留 branch 引用并按 resume 续做（worktree 在则原地、缺则从分支重建）；仅零提交才走现行清空重建。
- **清理协调**：shutdown/boot 的 orphan worktree 清理跳过被保全引用的 worktree。
- **worktree 可用性单源**：worktree_manager 暴露统一可用性查询（目录 + git worktree 注册 + 分支可解析），recovery/resume/复用认领共用（attempt 层 3a 校验已于 2026-09-05 落地）。

## Capabilities

### New Capabilities

- `interrupt-recovery-preserve`: 中断/重启场景下的成果保全与恢复续做——重启排水、终止前保全、恢复保留分支续做、清理协调、worktree 可用性单源。

### Modified Capabilities

（无——`agent-shutdown-interrupt`、`recovery-state-consistency` 等既有能力均已随历史 change 归档，本能力的非计划停机路径显式保持其既有语义零变化。）

## Impact

- **代码**：`fenixd.py`（shutdown 排水分支）、`bin/fenixd_supervisor.py`（SIGKILL 等待可配）、`core/state_machine.py`（recover_interrupted 保留判定）、`core/worktree_manager.py`（is_available 单源 + cleanup 协调）、`core/agent_runner/runner.py`（排水等待钩子）
- **配置**：`admin.shutdown_drain_seconds`（缺省 1800，0=保持现行快速停机）
- **运行时文件**：`.fenix/interrupted_runs.json`（新增 sidecar，kind: reference）
- **测试**：`tests/test_interrupt_recovery_preserve.py`（new）+ 既有 recovery/worktree 套件回归

## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: bin/fenixd_supervisor.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/worktree_manager.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: tests/test_interrupt_recovery_preserve.py
  kind: new
- path: .fenix/interrupted_runs.json
  kind: reference
```

## 1. worktree 可用性单源（纯重构，行为等价）

- [ ] 1.1 worktree_manager 新增 `is_available(spec_or_branch)` 三态查询（available/rebuildable/unavailable：目录存在 + `git worktree list` 注册有效 + 分支 `rev-parse --verify` 可解析），以 git 为真相、不信任内存表
- [ ] 1.2 `_take_reusable_worktree`、`runner._worktree_path_valid`（3a）、recovery 的目录/分支判定收敛到该查询（保留薄封装避免签名变更）

## 2. recovery 保留分支续做

- [ ] 2.1 `recover_interrupted` 改判定：interrupted implementing spec 分支存在且 `git rev-parse main..branch` 非空 → 保留 branch/implementer_run 并标记恢复续做；零提交/分支缺失走现行清空路径（逐字节兼容）
- [ ] 2.2 worktree 三态处置：在场原地续做；缺失但在既有分支上重建 worktree（复用 repair lane 1.2 的 checkout 能力）；不可用降级清空重建并 WARNING
- [ ] 2.3 恢复续做 spec 的 resume 派发复用既有继承语义（prompt 继承注记、attempt 校验、frozen/cancel 检查）

## 3. 终止前保全与清理协调

- [ ] 3.1 daemon 排水超时 terminate 在跑 run 前，写 `.fenix/interrupted_runs.json`（spec/run_id/branch/worktree/ahead_commits/reason/timestamp）；写入失败降级 WARNING 不阻塞停机
- [ ] 3.2 `cleanup_orphans` 增加保护集参数：跳过保全在册项与保留分支对应的 worktree；boot recovery 先完成保留判定再触发清理

## 4. 规划性重启排水

- [ ] 4.1 daemon SIGTERM 处理：restart_request 在册 → 排水模式（禁新派发 + 等待在跑 run 终态，上限 `admin.shutdown_drain_seconds` 缺省 1800、0=现行快速停机）；到期残留 run 按现行 terminate 流程收口；非计划 SIGTERM 行为零变化
- [ ] 4.2 supervisor SIGKILL 等待可配：读 `admin.shutdown_drain_seconds + 120s` 余量（解析失败回退 60s），保证排水期不被截断
- [ ] 4.3 排水状态可观测：日志记录排水开始/结束与等待的 run 清单；Dashboard 运维记录可见（复用既有日志流即可，不新增端点）

## 5. 测试与回归

- [ ] 5.1 tests/test_interrupt_recovery_preserve.py：覆盖 specs 全部 Scenario（排水等待/超时收口/非计划零变化、sidecar 先于 terminate、有提交保留续做/零提交兼容/worktree 重建、保全不被误删、三链路判定一致）
- [ ] 5.2 既有套件回归：recovery/worktree/runner 相关测试全绿（零提交路径与行为等价重构无差异）

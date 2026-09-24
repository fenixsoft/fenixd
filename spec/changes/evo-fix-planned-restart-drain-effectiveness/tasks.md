## Deliverables

```yaml
# ── 配置层：planned restart 豁免 shutdown=0 夹紧（A）──────────
- path: core/config.py
  kind: modify

# ── shutdown 路径：规划性重启取原值排水窗口 + 可观测（A/C）─────
- path: fenixd.py
  kind: modify

# ── runner：车道级在飞登记 API（B）──────────────────────────
- path: core/agent_runner/runner.py
  kind: modify

# ── ocr 车道：子进程登记进排水集合 + 超窗有序终止（B）──────────
- path: core/agent_runner/maintenance_runs.py
  kind: modify

# ── 测试 ──────────────────────────────────────────────────
- path: tests/test_planned_restart_drain_e2e.py
  kind: new
- path: tests/test_interrupt_recovery_preserve.py
  kind: modify

# ── 文档：运维联动说明与过渡配置 ─────────────────────────────
- path: docs/help/14-pipeline-throughput-ops.md
  kind: modify
```

## 1. 夹紧语义修正

- [ ] 1.1 core/config.py：get_run_drain_max_seconds 支持按规划性重启（planned restart）豁免 shutdown_drain_seconds=0 夹紧——规划性重启取 min(agents.run_drain_max_seconds 原值, supervisor SIGKILL 等待减终止收口安全余量)（shutdown≤0 时 SIGKILL 等待为 60s 回退，见 bin/fenixd_supervisor.py `_sigkill_wait_seconds`），非规划性关停保持现行 min 夹紧，shutdown_drain_seconds>0 部署行为不变
- [ ] 1.2 fenixd.py：shutdown 路径按 restart_request 在场判定取排水窗口；规划性重启但排水窗口为 0（配置禁用）时打 WARNING，排水启动时记录排水集合清单（在飞 run 与车道名）

## 2. 排水集合补全

- [ ] 2.1 core/agent_runner/runner.py：暴露车道级在飞登记/注销 API（register/unregister），供非 agent_runner 派生的车道进程进入 running_run_ids 排水集合（Popen 句柄跟踪，execvp 改名天然覆盖）
- [ ] 2.2 core/agent_runner/maintenance_runs.py：run_impl_ocr 的 ocr 子进程在飞期登记进排水集合；超窗时 SIGTERM+短宽限+SIGKILL 有序终止并落车道终态，重启后 serving worktree 不再被无主回收

## 3. 测试与文档

- [ ] 3.1 tests/test_planned_restart_drain_e2e.py：以替身进程驱动真实 shutdown 路径——在飞 evo 分析 run、implementer run、ocr 车道三者跨 restart_request 规划性重启，断言 run_drain_max_seconds 窗口内均不被 SIGTERM、超窗有序终止、checkpoint 旗标广播、ocr 车道有终态且 worktree 不被回收
- [ ] 3.2 tests/test_interrupt_recovery_preserve.py：test_drain_zero_fast_path 修订到新语义（fast path 仅非规划性关停；规划性重启不受 shutdown=0 夹紧），其余排水用例回归不变；并在 tests/test_pipeline_throughput_governance.py 补规划性豁免分支单测（planned 在场不受 shutdown=0 夹紧、窗口仍受 supervisor SIGKILL 等待上界约束），既有非规划性夹紧用例保持通过
- [ ] 3.3 docs/help/14-pipeline-throughput-ops.md：补 shutdown_drain_seconds 与 run_drain_max_seconds 联动说明、规划性重启排水语义、过渡期人工把 shutdown_drain_seconds 调正值的运维指引

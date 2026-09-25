## Deliverables

```yaml
# ── run 生命周期：取消旗标跨 attempt 生效 + retry 让位 + 停滞判停（A/B/C）──
- path: core/agent_runner/runner.py
  kind: modify

# ── 装配：并行出题标记读取回调注入（B）────────────────────────
- path: core/pm_engine/engine.py
  kind: modify

# ── 配置：agents.run_stall_budget_* 键规范化（C）────────────────
- path: core/config.py
  kind: modify

# ── 测试 ──────────────────────────────────────────────────
- path: tests/test_run_stop_loss.py
  kind: new
```

## 1. 取消旗标跨 attempt 生效与 retry 让位

- [x] 1.1 core/agent_runner/runner.py：cancel_run 的 not_running 分支改为按 base_id 登记取消旗标（复用 _normalize_run_id 归一化、_cancel_requested 幂等集合与 reason/by 元数据）后再返回，返回值保留 not_running 语义并附旗标登记标记；使 in-place retry 复活的 attempt 在启动守卫（_attempt_top_guards）处命中旗标以 cancelled 有序收尾，活跃 attempt 取消行为与 run 收尾旗标清理不变
- [x] 1.2 core/agent_runner/runner.py：in-place retry 重派前的让位判据对 planner-plan 增查并行出题标记 status 为 discarded 即放弃重派并让 run 以 cancelled 或 failure 收尾（标记实际枚举 dispatched/failed/discarded/completed，无 quarantined 值；产物隔离与 discarded 写入伴生）；标记读取以注入回调承载（缺省视为无标记、行为不变），不引入对 pm_engine 的模块依赖
- [x] 1.3 core/pm_engine/engine.py：装配侧经 runner 既有注入约定把并行出题标记读取（_read_parallel_plan_marker）传入 runner，让让位判据在真实派发链路生效

## 2. 停滞预算复合判停（缺省关闭）

- [ ] 2.1 core/agent_runner/runner.py：在流式循环既有 latency 采样点（latency_state 逐轮累积处）旁挂运行中判停，判据为 run 内连续 N 次以上达到 120 秒的往返、或 stall 占比达到一半且超过 M 分钟无产物 mtime 进展，命中走既有 attempt 终止与清理路径并在终态日志记录命中判据；判停统计随 run 生命周期累积、不随 attempt 重置，命中后终止整个重试链、不再触发瞬态重试或 in-place retry 重派；不新增 admin 告警
- [ ] 2.2 core/config.py：新增 agents.run_stall_budget_enabled、agents.run_stall_budget_stalls、agents.run_stall_budget_window_minutes 键规范化，缺省关闭、非法值回退缺省

## 3. 测试

- [ ] 3.1 tests/test_run_stop_loss.py：守卫测试用 seed 与进程内装配出题，覆盖 attempt 间隙取消路径——not_running 取消登记旗标后，复活 attempt 启动守卫命中旗标以 cancelled 收尾且不再执行 provider 轮次
- [ ] 3.2 tests/test_run_stop_loss.py：覆盖 discarded 标记下 in-place retry 让位不重派、标记在途或缺失时重试照常、活跃 attempt 取消行为不变三条路径
- [ ] 3.3 tests/test_run_stop_loss.py：停滞判据单元测试——复合判据各分支命中与不命中、慢而健康的 run 不误杀、缺省关闭时不判停、配置非法值回退缺省

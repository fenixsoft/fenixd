## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_code_review_night_defer.py
  kind: modify
- path: tests/test_code_review_night_resume.py
  kind: new
```

## 1. 保守跨窗估计

- [ ] 1.1 core/admin_monitor.py：周期审查派发守卫的预计时长估计由近 3 轮 duration_s 均值（core/admin_monitor.py:1921 一带）改为取同样本最大值，可用样本不足 3 时取已有样本最大值；窗相交判定逻辑不变
- [ ] 1.2 tests/test_code_review_night_defer.py：同步修正钉均值行为的既有断言——样本 10893/12500/5338（秒）时估计取 12500、01:00 派发预测结束落入 04:15-04:45 窗判顺延；可用样本不足 3 时取已有样本最大值

## 2. 锚驱动剃余续审

- [ ] 2.1 core/admin_monitor.py：周期审查派发链在读到 writeoff-pending 锚（core/code_review.py:1669-1692 API）时改用剩余清单派发——复用 429 限流重派已有的 remaining_manifest 组装路径（core/admin_monitor.py:2116-2138；core/code_review.py:260/:247），只在「全量清单 − 抢救已落账覆盖文件」上审查；无锚时行为不变
- [ ] 2.2 core/admin_monitor.py：续审 run 标注来源（如 resume_of=<死 run id>）并写结构化日志（reason=writeoff_resume、剩余分片/文件数）；收尾沿用既有累计覆盖守卫（core/agent_runner/maintenance_runs.py:2037-2060），覆盖完整走既有核销＋清锚路径，部分覆盖维持抢救红线不核销
- [ ] 2.3 tests/test_code_review_night_resume.py：覆盖三例——锚存在时剩余清单组装正确、无锚时全量清单行为不变、续审收尾累计覆盖完整时核销清锚

## 3. 回归

- [ ] 3.1 跑 tests/test_code_review_night_defer.py 与 tests/test_code_review_night_resume.py 全绿，并确认 tests/test_code_fix_night_quiet_window.py 的关键字缺席契约（maintenance_runs.py/event_bus.py 不得含 night_quiet_window）不破——本 SPEC 改动不触碰这两个文件
## Deliverables

```yaml
- path: fenixd.py
  kind: modify
- path: tests/test_supervisor_drift_log_dedup.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 fenixd.py：模块常量区新增 SUPERVISOR_LOG_DEDUP_MINUTES = 60（与 STALE_ALERT_DEDUP_MINUTES 同层声明）
- [ ] 1.2 fenixd.py：_check_supervisor_drain_consistency 的 warnings 追加循环前经 AdminStore.latest_signal 按 signal_type=supervisor_runtime_drift 做窗口去重，命中则跳过 _append_project_log 并写 logger.info 抑制说明；未命中则照常追加并写入一条 warning 级、写入即 mark_handled 的去重标记记录；admin_store 不可用或读写异常时降级为照常追加（保持现状行为）

## 2. 测试

- [ ] 2.1 tests/test_supervisor_drift_log_dedup.py：覆盖窗口内第二次启动不重复追加 PROJECT_LOG、超窗后新周期照常成条并写入去重标记、admin_store 缺失时降级追加三例
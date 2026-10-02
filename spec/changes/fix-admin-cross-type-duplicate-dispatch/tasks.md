## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_admin.py
  kind: modify
```

## 1. 宽口径统一与 exclude 透传

- [x] 1.1 `core/admin_monitor.py` 模块级 `_spec_has_active_admin_run` 增可选形参 `exclude_run_id=None`（透传 `_merge_admin_runs` 既有同名参数，缺省 None 零迁移——既有两个调用方 `_has_active_admin_run_for_spec` 与 `_recover_orphaned_dispositions` 孤儿扫描行为不变）
- [x] 1.2 周期摄取循环（STORED_SIGNAL_TYPES 分支的在飞互斥守卫，约 :2083）由 `_has_active_admin_run_for(spec, stype)` 换为 spec 单键口径；D2b 注释口径描述同步更正（「同 spec 同 signal_type」→「同 spec 任意 signal_type」）；跳过副作用逐字不变（不 mark_escalated、skipped 留痕 memo 去重每源一次）
- [x] 1.3 到期重派 `_retry_due_dispatch_failures`（约 :3320）换 spec 单键口径（注释中「另一信号类型或人工通道」的危害至此被真正守住）；跳过不 bump retry_count 语义不变
- [x] 1.4 孤儿重派 `_recover_orphaned_dispositions`（约 :3555）换 spec 单键口径并传 `exclude_run_id=rid`（排除被处理的中断 run 自身；spec=None 哨兵跳过判定的既有形态保持）
- [x] 1.5 窄口径方法 `AdminMonitor._has_active_admin_run_for` 调用点清零后删除（grep 全仓确认无残留引用，含测试）；`tests/test_admin.py` 补跨类型互斥用例：①摄取循环——spec 已有 `manual-intervention` 在飞 pending 时摄取 `verify_contract_missing` 信号 → 不唤起、源记录未消费；②到期重派——跨类型在飞时跳过且不 bump retry_count；③孤儿重派——自身 pending + 跨类型在飞 → 不重派；仅自身、无其他在飞 → 照常重派（exclude 语义保持）
- [x] 1.6 回归全绿：`python3 -m pytest tests/test_admin.py tests/test_event_bus.py tests/test_pm_verification.py -x -q`

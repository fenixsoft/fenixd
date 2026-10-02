## Deliverables

```yaml
- path: core/admin_monitor.py
  kind: modify
- path: tests/test_orphaned_state_signal.py
  kind: modify
```

## 1. 判定读侧扩展

- [ ] 1.1 core/admin_monitor.py：新增 helper（如 inprocess_verify_active）——(a) threading.enumerate() 命中 fenix-verifier-<spec> 活线程即 True（线程名从 queue.py 线程命名单点取值或抽公共常量，禁止两处硬编码）；(b) .fenix/verify-progress/<spec>.json mtime 落入独立活动窗口（新常量缺省 900s，对齐 DEFAULT_ORPHANED_STATE_THRESHOLD_MINUTES，与 ORPHANED_RUN_GRACE_SECONDS=120s 显式区隔并注释原因：单场景长批间隔实测 4-5 分钟）即 True
- [ ] 1.2 core/admin_monitor.py：spec_is_undriven 并入该 helper 作为条件⑤（任一命中判「有驱动」），docstring 按既有记忆惯例增补条件⑤由来（2026-10-02 cimbar-airgap-transfer 误报孤儿态+三批重复验证实证）；event_bus._recover_testing 经既有调用自动生效，如实现中发现调用形态差异需同步
- [ ] 1.3 core/admin_monitor.py：_reset_orphaned_after_disposition testing 分支重派前调 helper 复核，命中即顺延重派（保留复位语义，仅延后；线程退出/超窗后放行），堵第三放大器出口

## 2. 测试

- [ ] 2.1 tests/test_orphaned_state_signal.py：条件⑤——存在活 verifier 线程（threading 装置）时 spec_is_undriven 判有驱动；线程退出后判定与现状四条件口径完全一致（无新增豁免）
- [ ] 2.2 tests/test_orphaned_state_signal.py：进度文件 mtime 新鲜 → 豁免；超独立窗口 → 不豁免；含「120s 宽限不足而独立窗口豁免」的对照用例（os.utime 造 mtime 两态）；文件缺失 → 不豁免
- [ ] 2.3 tests/test_orphaned_state_signal.py：处置复位直通道在 verifier 线程活跃时顺延重派、线程退出后重派照常；顺延不产生重复告警/重复 transition
- [ ] 2.4 回归：tests/test_pm_recovery.py、tests/test_inconclusive_loop_escalation.py、tests/test_impl_ocr_parallel_lane.py 通过
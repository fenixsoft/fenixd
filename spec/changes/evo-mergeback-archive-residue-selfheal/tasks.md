## Deliverables

```yaml
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/pm_engine/dispatch/rollback.py
  kind: modify
- path: tests/test_mergeback_archive_residue_selfheal.py
  kind: new
```

## 1. 落地校验

- [ ] 1.1 core/pm_engine/dispatch/queue.py：_defer_merge_back（:2559）熔断出口前接入归档残留自愈评估——复用/抽取 _archive_move_residue（engine.py:2941）特征做只读判定，命中且脏文件全落 spec/ 路径时补提交归档收尾（add 限定 spec/changes 与 spec/archive、消息含目标 spec 名，补提交前重查工作区）并立即重放 merge-back，成功清理 _merge_retry_* 记账；未命中/失败走原熔断；单条至多自动尝试一次。
- [ ] 1.2 core/pm_engine/dispatch/rollback.py：_report_mergeback_spec_dir_inflight_stuck（:553）告警 evidence 增补自愈评估摘要（判据命中与否、补提交 hash、重放/失败原因）。
- [ ] 1.3 core/pm_engine/dispatch/queue.py：仿 _recheck_wip_deferred_merges（:2870，120 秒节拍）为无 _wip_gate_deferred 标志的 spec_dir_inflight 顺延条目建周期消费者，Timer 链中断后接手重试或按 spec_dir_inflight_grace_minutes（:2626）窗口降级。

## 2. 测试

- [ ] 2.1 tests/test_mergeback_archive_residue_selfheal.py：覆盖归档半程脏文件自动收尾+重放成功且零 admin 会话；混合源码 WIP 维持熔断；补提交失败熔断且 evidence 留痕；单次尝试上限；补提交前重查避免与归档自身收口并发重复提交；周期消费者在 Timer 链缺失时接手 pending 条目。
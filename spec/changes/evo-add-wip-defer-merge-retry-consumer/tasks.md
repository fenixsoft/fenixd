## Deliverables

```yaml
- path: core/pm_engine/dispatch/rollback.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/test_wip_defer_merge_retry.py
  kind: new
```

## 1. WIP 阻断落结构化载体

- [ ] 1.1 core/pm_engine/dispatch/rollback.py：_report_mergeback_wip_overlap 在写 error 的同次 update_spec 增写结构化等待标志（布尔 + 重试计数 + 首阻时刻），不再以 error 文本作为唯一现场标志
- [ ] 1.2 core/state_machine.py：把新标志登记进 STATE.md 布尔字段往返清单，并在 boot 清空路径与合并成功清账路径同步清除

## 2. 周期消费者

- [ ] 2.1 core/pm_engine/dispatch/queue.py：_retry_merge_back_only 前置状态守卫——仅 status=implementing 且带等待标志的 spec 可重试，已推进条目跳过并清账；周期复查方法实现逐条在主树锁内 merge-only 重试，成功走 _finalize_merge_success 推进并显式闭环 mergeback_wip_overlap 告警，失败计数 +1，超 90 分钟/6 次上限降级为人工处置告警并停止自动重试
- [ ] 2.2 fenixd.py：主循环增加独立计时器（参照 orphan_ready_check_ts 既有模式，120 秒节拍、try/except 不中断主循环）调用周期复查，先于 orphaned_state 探测生效

## 3. 测试

- [ ] 3.1 tests/test_wip_defer_merge_retry.py：覆盖 WIP 清理后自动合回推进 implemented 且告警闭环、人工已合并的 spec 不被重复合并（状态守卫）、超窗口或超轮数后停止自动重试并降级三个场景

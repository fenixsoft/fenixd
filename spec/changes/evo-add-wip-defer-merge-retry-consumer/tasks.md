## Deliverables

```yaml
- path: core/pm_engine/dispatch/rollback.py
  kind: modify
- path: core/pm_engine/dispatch/queue.py
  kind: modify
- path: core/state_machine.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: fenixd.py
  kind: modify
- path: tests/test_wip_defer_merge_retry.py
  kind: new
```

## 1. WIP 阻断落结构化载体

- [ ] 1.1 core/pm_engine/dispatch/rollback.py：_report_mergeback_wip_overlap 在写 error 的同次 update_spec 增写结构化等待标志（布尔 + 重试计数 + 首阻时刻），不再以 error 文本作为唯一现场标志
- [ ] 1.2 core/state_machine.py：把新标志登记进 STATE.md 布尔字段往返清单，并在三类写点同步清除——合并成功清账块（queue.py:2278-2281 同块）、boot 保留续做复位写点（implementing→READY，增写 _wip_gate_deferred=False）、boot 清空重建复位写点（对齐该处清 _repair_awaiting_remerge 的既有条目）；两个 boot 复位写点漏清会导致重启后陈旧标志在恢复 run 在飞期间触发过早合并

## 2. 周期消费者

- [ ] 2.1 core/pm_engine/dispatch/queue.py：守卫拆两层，勿写成单条「须带 wip 标志才放行」（既有 spec_dir_inflight 顺延定时器链的条目仅带 _merge_retry_pending、既有测试直调不带标志，均须继续可用）——(a) _retry_merge_back_only 前置 status 守卫：status 非 implementing 即跳过并清账后返回（人工/admin 已推进条目不再重复合并）；(b) 新增周期复查方法：扫描仅认 status=implementing 且 _wip_gate_deferred 为真的条目，逐条在主树锁内 merge-only 重试，成功走 _finalize_merge_success 推进并显式闭环 mergeback_wip_overlap 告警（写 result=resolved 处置记录），失败计数 +1，超 90 分钟/6 次上限降级为人工处置告警并停止自动重试
- [ ] 2.2 fenixd.py：主循环增加独立计时器（参照 orphan_ready_check_ts 既有模式，120 秒节拍、try/except 不中断主循环）调用周期复查，先于 orphaned_state 探测生效
- [ ] 2.3 core/admin_monitor.py：_detect_orphaned_state 增设与 _repair_awaiting_remerge 同型豁免——_wip_gate_deferred=True 且未超限（计数<6 且窗口<90 分钟）的 implementing 条目跳过探测；超限降级后豁免自动失效，孤儿探测恢复兜底

## 3. 测试

- [ ] 3.1 tests/test_wip_defer_merge_retry.py：覆盖 WIP 清理后自动合回推进 implemented 且告警闭环、人工已合并的 spec 不被重复合并（状态守卫）、超窗口或超轮数后停止自动重试并降级、带标志未超限条目豁免 orphaned_state 且超限后恢复探测、boot 复位写点清除标志（重启后恢复 run 在飞期间不触发重试）等场景

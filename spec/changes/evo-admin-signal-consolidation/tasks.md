# 任务

## Deliverables

```yaml
- path: core/admin_store.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
```

## 1. 信号记录扩展 status_hash/first_seen/last_seen 与去重合并

- [x] 1.1 core/admin_store.py：新增 per-spec 信号沉淀方法（合并同 (spec, signal_type) 同 status_hash 记录，仅刷 last_seen，保留 id/created/escalated/handled）；不修改 `append` 的全局语义。
- [x] 1.2 core/admin_store.py：`latest_signal` 窗口判定改为 `max(created,last_seen)`，无 last_seen 的历史记录仍按 created 判定；补测试覆盖「沉淀后跨越 cooldown 窗口仍命中节流」及既有外部调用点（dispatch_stalled / instant_fail_storm / transient_break_storm / verify 告警）语义不变。
- [x] 1.3 写单元测试覆盖「状态未变仅更新 last_seen」「状态变化新建记录」「escalation 与写入即待唤起记录不被合并」「spec=None 按声明口径处理」。

## 2. admin_monitor 状态哈希判定与悬置 ≥2h 强制升级

- [x] 2.1 core/admin_monitor.py：计算 status_hash 判定状态未变；相同则调用沉淀方法，不新增记录、不打重复日志。
- [x] 2.2 core/admin_monitor.py：对悬置类信号（blocked_stuck + ENV 阻塞族），`now − spec.updated ≥ 2h`（模块常量，不入 config）且 `unhandled_for(spec, signal_type)` 为空时，直接写 `kind=escalation`（severity critical，含悬置时长与 first_seen），不重新唤起 Administrator；绕过 cooldown 但受未处理告警约束。
- [x] 2.3 写测试覆盖：9.5h 悬置重放 ≤2 条记录且 Administration 不重复唤起；跨 cooldown 窗口不重复唤起；未处理升级存在时不新增；人工 handled 后仍悬置可再升级；非悬置类信号 >2h 不触发强制升级。

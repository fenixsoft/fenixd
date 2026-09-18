# admin-disposition-reschedule

## 定位

AdminMonitor 孤儿处置（_recover_orphaned_dispositions）对「known shutdown 中断的 admin run」的收尾策略：从「静默终结」升级为「按底层信号未处理状态自动重派」。

## 术语

- known shutdown 中断：run 转录文件含 interrupted 标记（_run_has_interrupted_marker 判定），表示 daemon 优雅退出导致的 run 中断。
- 底层信号：admin_alerts.json 中 kind=signal 且 escalated=true 的记录（如 verify_contract_missing），是用户请求与待办工作的持久来源。

## 场景

### Scenario: 信号未处理 → 中断后自动重派

- Given 一个 kind=signal 记录（handled=false）曾唤起 admin run R1
- And R1 因 daemon 优雅退出被中断（转录含 interrupted 标记，pending disposition 超时）
- When _recover_orphaned_dispositions 处理该 disposition
- Then 不终结为 interrupted
- And 自动重新入队新的 admin run（新 admin_run_id）
- And 新 disposition status=dispatched，actions_taken 注明 rescheduled from R1
- And 原 pending disposition 置为 superseded（而非 interrupted）

### Scenario: 信号已处理 → 正常终结

- Given 底层信号已 handled=true
- When 孤儿检测遇到对应中断 run
- Then 维持现状：终结为 interrupted，不重派

### Scenario: 重派超限 → 升级人工

- Given 同信号累计重派次数达到上限（默认 2）
- And 新 run 再次被中断
- When 孤儿检测再次处理
- Then 产生一条 kind=escalation 人工告警（severity critical，注明中断次数）
- And 不再自动重派

### Scenario: 并发去重

- Given 同信号已存在在飞/待派发的 admin run
- When 重派判定执行
- Then 跳过重派（复用既有去重/并发守卫），避免双重派发

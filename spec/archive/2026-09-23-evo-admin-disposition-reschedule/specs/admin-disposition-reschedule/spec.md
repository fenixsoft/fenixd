# admin-disposition-reschedule

## 定位

AdminMonitor 孤儿处置（_recover_orphaned_dispositions）对「known shutdown 中断的 admin run」的收尾策略：从「静默终结」升级为「按底层信号未处理状态自动重派」。

## 术语

- known shutdown 中断：run 转录文件含 interrupted 标记（_run_has_interrupted_marker 判定），表示 daemon 优雅退出导致的 run 中断。
- 底层信号：admin_alerts.json 中 kind=signal ∧ escalated=true ∧ 非 handled 的记录，是「用户请求 / 待办工作」的持久来源；匹配口径为 (signal_type, spec) 严格相等。
  - escalated=true 口径的依据：仅在实际唤起 Administrator 时（节流通过）才以 escalated=true 落信号记录（admin_monitor.py:1365-1370），节流分支落 escalated=False（1330-1333）。以 escalated=true 匹配可避免为「从未唤起过的节流沉淀记录」发起重派。
  - spec 严格相等口径的依据：实测现有 50 条 kind=signal 记录的 spec 全部非 None，且手动唤起路径强制携带 spec（core/signals.py:74、core/dashboard/routes/spec_routes.py:662）；不存在「信号 spec=None vs disposition spec=项目名」的字段差异，故不做宽松匹配。
- reschedule_count：信号族 (spec, signal_type) 的累计重派次数，落库在 DISPOSITION 记录的 `reschedule_count` 字段，读取时取该族记录中的最大值（缺省 0）。

## 场景

### Scenario: 信号未处理 → 中断后自动重派

- Given 一个 kind=signal 记录（escalated=true ∧ handled=false）曾唤起 admin run R1
- And R1 因 daemon 优雅退出被中断（转录含 interrupted 标记，pending disposition 超时）
- And 该信号无在飞/待派发 admin run（无同 (spec, signal_type) 的 status=pending disposition）
- When _recover_orphaned_dispositions 处理该 disposition
- Then 不终结为 interrupted
- And 调用 _invoke_administrator 重新入队新的 admin run（新 admin_run_id，由 run_administrator 自行落 pending 记录）
- And 原 pending disposition 追加 status=superseded 记录（同原 admin_run_id），actions_taken 注明 rescheduled from R1，并携带 reschedule_count=旧值+1
- And MUST NOT 为新增 run 追加 status=dispatched 记录——同 admin_run_id 的非 pending 记录会使 by_run 归并把该 run 判为 final，令孤儿检测对该 run 永久失效

### Scenario: 无未处理信号 → 正常终结

- Given 该 (spec, signal_type) 已无 escalated=true ∧ 非 handled 的信号记录
- When 孤儿检测遇到对应中断 run
- Then 维持现状：终结为 interrupted，不重派

### Scenario: 重派超限 → 升级人工

- Given 同 (spec, signal_type) 累计 reschedule_count 已达上限（默认 2，即已重派 2 次）
- And 新 run 再次被中断
- When 孤儿检测再次处理
- Then 产生一条 kind=escalation 人工告警（severity critical，注明中断/重派次数）
- And 为该 run 追加非 pending 终结 disposition（status=escalated），防每轮巡检重复升级
- And 不再自动重派

### Scenario: 并发去重

- Given 同 (spec, signal_type) 已存在在飞/待派发的 admin run（存在 status=pending 的 DISPOSITION 记录）
- When 重派判定执行
- Then 跳过重派（新增 `_has_active_admin_run_for` 判定，判据对齐 by_run 归并的 pending 口径），避免双重派发

### Scenario: 重派后的 run 再次被中断 → 计数递增

- Given 重派产生的新 run R2 的 pending disposition 超时
- And R2 转录含 interrupted 标记
- Then 孤儿检测检出该 pending（by_run 归并未因其非 pending 兄弟记录而误判 final）
- And 按 reschedule_count=1 → 2 的节奏再判定一次：未超限则再重派，超限则升级人工

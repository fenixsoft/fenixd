# 实现设计

## 现状

core/admin_monitor.py:1431 _recover_orphaned_dispositions（核心循环）：
1. 分组收集 pending disposition（admin_run_id 维度）
2. 超时（grace = cooldown ≥ 60m）后：有未处理 escalation → continue；有 interrupted 标记 → 终结 interrupted（1474-1494）；否则 → escalation（1496-1515）

admin_store.py:502 unhandled_for 只匹配 kind=ESCALATION，不匹配 kind=signal——信号 spec=None vs disposition spec=项目名的字段不一致进一步弱化匹配。

## 方案

### 底层信号回溯

新增 admin_store.unhandled_signal_for(spec, signal_type)：匹配 kind=signal 且 handled=false 的记录。spec=None 视为宽松匹配（兼容 ui-manual 触发的信号 spec=None 与 disposition spec=项目名的字段差异）。

### 重派判定（1474 分支前置改造）

已知中断分支处理前，按 (spec, signal_type) 调用 unhandled_signal_for：
- 找到且 handled=false → 自动重派（见下）
- 未找到 / handled=true → 维持现终结逻辑

### 重派执行

复用 _invoke_administrator(signal, signal_rec)（admin_monitor.py 现派发入口）。重派前：
1. 去重：_has_active_admin_run_for(spec, signal_type) —— 该信号无在飞/待派发 admin run 才派（同 fix-admin-self-heal 兼容）
2. 计数：从原 disposition 链读 reschedule_count（原为 0），累计到达 MAX_RESCHEDULE（默认 2，模块常量）→ 转升级分支，升级记录中注明累计中断/重派次数

### 审计留痕

- 新 disposition：status=dispatched，admin_run_id=新 run id，actions_taken='rescheduled from interrupted disposition <old_id> (signal <sig_id> still unhandled)'
- 原 pending disposition：status=superseded，actions_taken='superseded by rescheduled disposition <new_id>'（保留审计链）
- MAX_RESCHEDULE 为模块常量，config 可覆盖（admin.reschedule_max）

## 失败模式

- 重派后再次中断但信号仍未处理 → 计数 +1，直到超限升级（避免无限循环烧钱）
- store 并发写：disposition 追加沿用现 record 追加语义（append 幂等）
- daemon 在重派 run 在飞时再次停机 → 下一轮孤儿检测重复上述逻辑，幂等

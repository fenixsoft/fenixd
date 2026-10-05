## 能力：code-fix 夜间静默窗投递守卫

code-fix 批投递入口（CodeFixOrchestrator.checkpoint()）在本地时间落入配置的每日静默窗时拒绝启动新批并留痕，窗末自动恢复投递。

### 需求

1. 静默窗以本地时刻表达，形如 "HH:MM-HH:MM"，首版只要求单日内区间（本场景 04:15-04:45），不要求跨午夜。
2. 配置键沿用本车道既有取值模式（_switch_cooldown_seconds 读取的 admin.code_review_fix.* 点号键，core/code_fix.py:2646），新增 night_quiet_window，缺省 "04:15-04:45"（依据：死亡集中于 04:31-04:34，断窗本体 04:30:01-04:31:23 加 DNS 余波；窗起点须早于批链典型批时长对应的最早在飞启动时刻），设为空串或 off 时完全禁用。
3. 判定位置：checkpoint()（core/code_fix.py:2813）既有 switch_cooldown 守卫块（:2935-3010）同级新增静默窗分支；窗内返回 triggered=False、reason=night_quiet_window，并写与冷却同形态的武装/解除告警（复用 _write_switch_cooldown_alert :2301 / _write_switch_cooldown_release_alert :2341 形态），evidence 含窗区间与下一可投递时刻。
4. 与既有冷却同时命中时，可投递时刻取更晚者；二者独立武装/解除，互不复位对方。
5. 三路触发（批收尾自驱动 _resubmit :3369、full-scan 兜底 core/event_bus.py:274、持有者终态回调 :3643）均经 checkpoint() 汇入，入口单点判定即可全覆盖；须以测试固定该不变量。
6. 静默窗判定使用本地时区（与断窗时刻对齐），实现须显式取本地时间而非 UTC。

### 验收

- 窗内触发 checkpoint() 不产生新批、武装告警可见；窗末首次触发恢复投递并落解除告警。
- 配置禁用后行为与现状一致。
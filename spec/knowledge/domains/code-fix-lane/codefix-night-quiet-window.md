# code-fix 夜间静默窗投递守卫

<!-- knowledge: capability=codefix-night-quiet-window rev=1
     sources=spec/archive/2026-10-13-evo-codefix-night-quiet-window -->

code-fix 批投递入口在本地每日静默窗内拒绝启动新批并留痕，窗末自动恢复投递，使批次不会被启动进已知的上游周期断窗。

## 规则

- 静默窗以本地时刻表达，格式 `HH:MM-HH:MM`，为单日内区间（不要求跨午夜）；判定使用本地时区，实现显式取本地时间。区间端点为「起点含、终点不含」：以缺省窗为例，04:15:00 起拦截、04:45:00 起放行。
- 配置键 `admin.code_review_fix.night_quiet_window`，缺省 `"04:15-04:45"`；设为空串或 `off` 时完全禁用，禁用后行为与无守卫一致。沿车道取值模式：点号键 + 代码内缺省常量，不在配置模板强配。
- 解析失败（格式非法，含 end<=start 逆序区间）一律按无窗处理，并记一次 WARNING，防配置错误静默吞掉拦截语义。
- 判定位置在 `CodeFixOrchestrator.checkpoint()` 既有 switch_cooldown 守卫块同级：窗内返回 `triggered=False`、`reason=night_quiet_window`，不产生新批。四路触发（批收尾自驱动 _resubmit、审查收尾新条目激活、event_bus full-scan 兜底、持有者终态回调）均经 checkpoint() 汇入，入口单点判定即全覆盖，有测试固定该不变量。
- 留痕按「窗次」幂等，窗次标识含日期：首次进入窗内写武装告警，窗末首个放行触发写解除告警，evidence 含窗区间与下一可投递时刻；同窗次武装/解除各至多一次，跨窗次自动重新武装；残留窗次标识不拦截投递（惰性清理）。
- 与 switch_cooldown 冷却同时命中时，可投递时刻取更晚者，返回的 reason 取更晚可投递者对应的守卫；二者独立武装/解除，互不复位对方。
- 守卫位于 checkpoint() 公共路径，对手动触发同样生效：`override_enabled=True` 手动授权仅越过 enabled 总开关，不越过静默窗守卫；窗内手动触发回链 `triggered=False`、`reason=night_quiet_window`，属预期行为非回归。
- 手动触发回链文案由 `fenixd.py` 的 CODE_FIX_RESULT_MESSAGES 提供 night_quiet_window 中文条目；条目缺项回退为原始 reason 串。

## 关键行为

窗内任一路触发 checkpoint() → 拒绝启动新批并按窗次武装留痕一次 → 窗末首个 checkpoint() 放行投递并落解除留痕 → 批链恢复。窗口外的连接类瞬态不受本守卫影响，仍由连接类失败短冷却与 api_timeout salvage 事后兜底；在跑长批横跨窗口的死亡不在此防线内，同由 salvage 兜底。

## 溯源

- 2026-10-13 evo-codefix-night-quiet-window（spec/archive/2026-10-13-evo-codefix-night-quiet-window） — 新建本页：每日静默窗投递守卫全部规则（窗格式与本地时区判定、配置键与禁用/降级语义、checkpoint 单点判定全覆盖、窗次幂等武装/解除留痕、与冷却共存取更晚、手动触发同受守卫与回链文案）。

# code-fix 夜间静默窗投递守卫

<!-- knowledge: capability=codefix-night-quiet-window rev=3
     sources=spec/archive/2026-10-13-evo-codefix-night-quiet-window,spec/archive/2026-10-26-evo-add-night-window-inflight-guard,spec/archive/2026-10-30-evo-add-review-night-defer-snapshot-writeoff -->

code-fix 批投递入口对「派发时刻落窗」与「窗前派出、预计窗中在飞」两类形态都拒绝把新批送进本地每日静默窗（窗模型为多窗列表，命中任一窗即避让），窗末自动恢复投递，使批次不被启动进已知的上游周期断窗。

## 规则

- 静默窗以本地时刻表达，配置为逗号或分号分隔的「HH:MM-HH:MM」区间列表（单窗字符串按单元素列表解析，行为不变）；区间为单日内区间（不要求跨午夜），判定使用本地时区，实现显式取本地时间。区间端点为「起点含、终点不含」：以 04:15-04:45 段为例，04:15:00 起拦截、04:45:00 起放行。
- 配置键 `admin.code_review_fix.night_quiet_window`，缺省 `"03:00-03:15,04:15-04:45"`（多窗缺省——04:15 窗覆盖 04:30 断窗本体，03:00 窗覆盖 kern.log 观测的散布断窗波，缺省即覆盖已观测散布形态；全部消费点经同一解析器生效）；设为空串或 `off` 时完全禁用，禁用后行为与无守卫一致。沿车道取值模式：点号键 + 代码内缺省常量，不在配置模板强配。
- 解析任一段非法（缺分隔符、非 HH:MM、时分越界、end<=start 逆序、空段）一律整体按无窗处理（宁缺毋错，不部分生效），并按「一次」纪律记 WARNING（同实例对同一非法值只告警一次，值变更后重新告警），防配置错误静默吞掉拦截语义。
- 命中判定为「任一窗 start<=cur<end」：命中任一窗即避让；多窗同时命中取最晚窗末为下一可投递时刻；窗次幂等键含命中窗文本，同日多窗各自武装/解除一次。
- 投递判定覆盖两类落窗形态：其一为当前时刻已落窗；其二为预计跨窗——当前时刻在窗前，但批次预计结束时刻（当前时刻 + 同链近批实测时长均值）与窗区间相交，同样顺延到窗末。预计结束时刻早于窗起点（恰压线视作不相交）则按原时刻投递，不为能赶在窗前完成的批次引入额外延迟。
- 预计时长取同链近批实测均时长，对慢批次自适应；时长数据源为 run_metrics 行的 `duration_s` 字段（归档行与日志行两处同源写入）。同链近批无有效样本时（新链冷启动或历史行未记时长）回退「仅判派发时刻落窗」判定、照常投递——缺样 fail-open，MUST NOT 因缺样阻塞投递。
- 判定位置在 `CodeFixOrchestrator.checkpoint()` 既有 switch_cooldown 守卫块同级：落窗或预计跨窗返回 `triggered=False`、`reason=night_quiet_window`，不产生新批。四路触发（批收尾自驱动 _resubmit、审查收尾新条目激活、event_bus full-scan 兜底、持有者终态回调）均经 checkpoint() 汇入，入口单点判定即全覆盖，有测试固定该不变量。
- 留痕按「窗次」幂等，窗次标识含日期与命中窗文本：首次拦截写武装告警，窗末首个放行触发写解除告警，evidence 含窗区间与下一可投递时刻；同窗次武装/解除各至多一次，跨窗次自动重新武装；残留窗次标识不拦截投递（惰性清理）。
- 与 switch_cooldown 冷却同时命中时，可投递时刻取更晚者，返回的 reason 取更晚可投递者对应的守卫；二者独立武装/解除，互不复位对方。
- 守卫位于 checkpoint() 公共路径，对手动触发同样生效：`override_enabled=True` 手动授权仅越过 enabled 总开关，不越过静默窗守卫；窗内手动触发回链 `triggered=False`、`reason=night_quiet_window`，属预期行为非回归。
- 手动触发回链文案由 `fenixd.py` 的 CODE_FIX_RESULT_MESSAGES 提供 night_quiet_window 中文条目；条目缺项回退为原始 reason 串。
- 该静默窗是多路消费点的唯一窗源（admin 唤起避让闸、自进化检查点避让、周期代码审查派发顺延）：复用同一配置键与窗解析，不设第二份窗配置。admin 侧避让语义见 [administrator-agent](../admin-ops/administrator-agent.md)；自进化侧为检查点派发前「派发时刻＋近几轮归档时长估计」与窗列表的相交判定，命中即本轮跳过（reason=night_quiet_window_deferred），不消费水位/就绪标记；周期代码审查侧为守卫链内跨窗顺延判定（细节见 [code-review-agent](../code-review-lane/code-review-agent.md)）。

## 关键行为

任一路触发 checkpoint() → 同时判定「当前落窗」与「预计跨窗」两种形态，逐窗比对窗列表 → 命中任一窗即拒绝启动新批并按窗次武装留痕一次 → 窗末首个 checkpoint() 放行投递并落解除留痕 → 批链恢复。预计不跨窗的批次按原时刻投递；缺时长样本回退仅判落窗。窗口外的连接类瞬态不受本守卫影响，仍由连接类失败短冷却与 api_timeout salvage 事后兜底；已派出批次横跨窗口的在飞死亡不在此防线内（不做窗前主动回收），同由 salvage/超时监督兜底。

## 溯源

- 2026-10-13 evo-codefix-night-quiet-window（spec/archive/2026-10-13-evo-codefix-night-quiet-window） — 新建本页：每日静默窗投递守卫全部规则（窗格式与本地时区判定、配置键与禁用/降级语义、checkpoint 单点判定全覆盖、窗次幂等武装/解除留痕、与冷却共存取更晚、手动触发同受守卫与回链文案）。
- 2026-10-26 evo-add-night-window-inflight-guard（spec/archive/2026-10-26-evo-add-night-window-inflight-guard） — 投递判定新增「预计跨窗」形态：近批实测均时长估计预计结束时刻、与窗区间相交即顺延窗末、预计不跨窗不引入延迟、run_metrics 写入侧补记 duration_s、缺样 fail-open 回退仅判落窗。
- 2026-10-30 evo-night-window-guard-coverage-closure — 缺省窗多窗化为「03:00-03:15,04:15-04:45」（散布断窗纳入缺省覆盖）；自进化检查点接入同源跨窗避让（命中跳过、reason=night_quiet_window_deferred、不消费水位/就绪标记）；维护车道派发前新增连通预检（DNS 探测失败顺延派发、探测异常 fail-open）。
- 2026-10-30 evo-add-review-night-defer-snapshot-writeoff（spec/archive/2026-10-30-evo-add-review-night-defer-snapshot-writeoff） — 窗模型多窗化：解析升级为逗号/分号分隔多窗列表（任一段非法整体无窗不部分生效、单窗输入行为不变、空串/off 禁用语义不变），code-fix 守卫与 admin 避让全部消费点改读窗列表（命中任一窗避让、多窗同中取最晚窗末、窗次幂等键含命中窗文本）。

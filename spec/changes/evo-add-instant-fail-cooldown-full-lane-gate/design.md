# design：秒挂冷却全车道门控与到期复诵

## 现状与改动面

- 计数与冷却状态：core/agent_runner/runner.py `_instant_fail[spec]`（惰性 dict，纯内存；:7721-7734 配置缺省阈值 3/300 秒、判定阈值 60 秒；:7835-7888 `_record_instant_fail` 入账；:7943-7960 到期清零在查询侧 pop）。
- 现有门控点：core/pm_engine/dispatch/queue.py:738-750（仅 implementer/fast-track，位于 `_entry_dispatchable`，命中返回 False 即不 pop 不耗预算）；core/pm_engine/dispatch/repair_lane.py:269（repair）。
- 管理员通道：core/admin_monitor.py 已有 3 处 signal-kill 冷却检查（:4829/:5144/:6122，含完整跳过留痕模式）可并列复用。
- 到期恢复定时器：core/pm_engine/dispatch/backoff.py:330-340 `_fire_recovery_callback`、:366-374 回调触发的重入；共用排程器 `_schedule_recovery_timer`（backoff.py:300-301，秒挂/信号死法两通道共用）现有判重早退（冷却被续写时定时器不重排）。

## 方案

1. 门控面扩展（queue.py）：把 :738 的 atype 元组扩为 implementer/fast-track/planner-plan/verifier（以代码内常量集合表达，与 run_id 前缀表解耦）；复用 `_instant_fail_cooled(spec)` 既有查询，不新增状态。跳过留痕升 INFO：参照同文件 transient 首道闸 :817-823 的 INFO 先例，记录 spec 名、被拦车道、剩余冷却秒数；同步修正 runner.py:7884-7886 ERROR 文案的门控面描述。verifier 派发确认与 planner 同走 `_entry_dispatchable`（:694/:712 两处入口都过闸），避免旁路。
2. 管理员纳管（admin_monitor.py）：在 :4829/:5144/:6122 同点位并列加 `_instant_fail_cooled(spec)` 判定，仅当 signal 带 spec 归属时生效；spec=null 的全局唤起直接放行。留痕沿用 signal-kill 的跳过日志模式。
3. 复诵与翻倍（runner.py + backoff.py）：
   - `_record_instant_fail` 在 `_instant_fail[spec]` 增记两个字段：归一化故障指纹（对 error 原文做路径/端口/run id 归一化，语义对齐 daemon_errors 指纹通道）与末次失败时刻。
   - 到期路径改造：现查询侧 pop 清零（runner.py:7943-7960）改为「先复诵后消费」——若末次失败时刻严格晚于本次冷却起点（起点 = 进入/续写冷却的写入时刻；引发本次冷却的失败批次与起点同刻，不触发复诵。冷却窗内有新失败，含非门控车道喂入），不清零：翻倍次数 +1（上限 3 次，独立于秒挂连击 count），冷却时长 = min(当前×2, 2400)，续写 cooldown_until 并让 backoff 定时器按新截止重排（共用排程器 `_schedule_recovery_timer` 的判重早退放宽为「截止时刻变化即重排」，backoff.py:300-301）；否则清零恢复。查询侧读改写 MUST 持 `_instant_fail_lock` 临界区（对齐 runner.py:7856-7862 先例）。指纹字段用于续冷却留痕与未来复诵扩展，翻倍判定本身以「窗内有无新失败」为准，避免指纹归一化误差阻塞恢复。
   - 防饿死边界：翻倍上限 3 次/封顶 2400 秒保证最坏 40 分钟后必恢复派发，与既有悬空超时兜底（8 小时）保持足够代差。
4. 兼容与风险：
   - verifier 被门控最多延迟验证链收尾 300 秒/窗（队列保留重判），与 implementer 今日被门控的既有风险同量级。
   - 计数按 spec 维度不变：非门控车道入账失败仍推计数（改为触发更早的全车道暂停），这是预期行为；门控扩展后窗内非门控车道不再新派，计数爬升源头同步收敛。
   - 残留非门控车道：spec-review 条目不入闸（本次事故证据面为出题/验证/管理员派发点），reviewing 状态 spec 的评审 run 秒挂仍按既有 count≥3 续写 cooldown_until 语义（runner.py:7870-7871）反向延长冷却——与现状同量级，属已知范围裁剪，不另立机制。
   - 纯内存状态、重启即清语义不变。

## 测试策略

新文件 tests/test_instant_fail_cooldown_gate.py 用进程内装配（seed + 假 runner）覆盖：planner/verifier 冷却跳过与到期自动重判、implementer/fast-track/repair 不回归、admin spec 作用域门控与全局放行、到期复诵翻倍与封顶、窗内零新失败正常恢复。回归跑 test_pm_dispatch.py、test_verify_dispatch_single_flight.py、test_admin_dispatch_*.py 确认派发时序不破坏；另 MUST 回归 tests/test_transient_backoff.py（§6.1 直测 _record_instant_fail 计数/重置语义）与 test_verify_lane_throughput.py，并断言信号死法冷却恢复定时器不回归（复诵定时器适配改的是两通道共用的 _schedule_recovery_timer）。
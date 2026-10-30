# proposal：秒挂冷却全车道门控与到期复诵

## 问题

秒挂冷却（连续 3 次、300 秒）是进程启动类基础设施故障的熔断机制，但门控面只有 implementer/fast-track/repair 三车道白名单（core/pm_engine/dispatch/queue.py:738-750、core/pm_engine/dispatch/repair_lane.py:269），planner/verifier/administrator 派发点零检查。2026-10-14 add-harness-brand-projection 的 dsh 补丁互踩风暴实测：两个冷却窗（04:39-04:50Z）内门控面车道零新派发（白名单内门控是生效的），而非门控车道实新派 6 次（planner 1791953127/3256/3316/3376 + verifier 1791952773 + 首窗到期 0.3 秒后沿旧指纹复发的 1791953098），全部 3 attempt 秒死、0 token 空转；非门控车道的 12 次 attempt 还把连续秒挂计数从 6 推到 18，每次 count≥3 续写 cooldown_until，反向延长门控面车道的停摆。缺口为设计层已知欠账：归档 spec 2026-09-22-evo-sigterm-source-tracking-cooldown 的 spec.md 明文对比过两通道覆盖面，signal-kill 通道当时做了全车道、秒挂通道未同步。触发条件呈复发趋势：40 天仅有的 2 次冷却事件（10-02、10-14）全部落在近 12 天，与 dsh 升默认车道同步。另实测「到期即重进故障循环」形态：1791953098 启动于首窗到期后 0.3 秒、随即再死；且闸门跳过只记 DEBUG（生产日志零 DEBUG，core/pm_engine/dispatch/queue.py:815 自认），门控是否生效无法从日志留痕判断。

## 目标

1. 门控面从三车道白名单改为按故障面覆盖：planner-plan 与 verifier 派发纳入秒挂闸门（保留既有队列语义：命中即跳过、不 pop、不耗预算）；管理员仅 spec 作用域处置唤起纳入（与既有 signal-kill 冷却检查同点位并列），daemon_errors 全局信号（spec=null）唤起保持放行，不锁死故障期的自救通道。
2. 冷却到期改为「复诵恢复」：到期时若冷却窗内该 spec 仍有新秒挂记录（末次失败时刻晚于冷却起点），不清零而是冷却时长翻倍（最多 3 次、封顶 2400 秒）并重排恢复定时器；窗内零新失败或故障指纹消失才恢复——消除到期即重派的故障循环形态。
3. 门控跳过留痕从 DEBUG 升 INFO（spec 名、车道、剩余冷却秒数），使门控生效可从日志直接核验。

## 非目标

- 不改秒挂判定口径（存活 <60s 判秒挂、阈值 3、计数按 spec 维度）与 implementer/fast-track/repair 既有过闸行为；
- 不做跨 spec 全局派发熔断（冷却仍按 spec 维度）；
- 不动 daemon_errors 全局信号的唤起与冷却语义（相邻主题另有在途工作）；
- 不做冷却状态持久化（维持纯内存、重启即清的现语义）。
<!-- knowledge: capability=cli-retry-backoff rev=1 sources=spec/archive/2026-09-10-run-lifecycle-hardening -->

# CLI 秒挂退避冷却

同一 SPEC 连续秒级失败时的 spec 级调度冷却：防秒挂风暴空烧派发与进程，同时不干扰 provider 熔断语义。

## 现行规则

- run 进程存活时长低于秒挂判定阈值（`agents.instant_fail_threshold_seconds`，缺省 60 秒）即死亡、且连续失败次数达到 `agents.instant_fail_cooldown_after`（缺省 3 次）时，daemon 对该 spec 启动冷却：时长 `agents.instant_fail_cooldown_seconds`（缺省 300 秒）。冷却期内所有 implementer/fast-track/repair 派发请求被跳过（记 DEBUG 日志，不消耗实现预算、不启动新 claude 进程）；冷却到期后自动恢复正常调度，连续失败计数从 0 重新累计。
- 两次秒挂之间出现一次成功 run 或一次存活超过阈值的失败 run 时，连续计数归零重新累计（非连续失败不累积）。
- 冷却首次触发时发出一条 major 级人工告警（signal_type=`instant_fail_storm`，含 spec 名、连续失败次数与冷却安排）；同一 spec 的重复冷却在既有 15 分钟告警节流窗内不重复告警。
- 与 provider 熔断正交：秒挂计数不进入 provider 熔断窗口，provider 熔断（4xx circuit）也不重置 spec 秒挂计数；两机制各自独立生效与解除。

## 溯源

- 2026-09-10 run-lifecycle-hardening（spec/archive/2026-09-10-run-lifecycle-hardening） — 确立连续秒挂的 spec 级退避冷却（阈值/次数/时长三配置键）、风暴告警与 provider 熔断正交语义

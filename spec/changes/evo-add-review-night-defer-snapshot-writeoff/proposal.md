# Why

2026-10-10 03:00 链路抖动（kern.log：03:00:01 Down→03:01:23 恢复）击杀了跑满 118 分钟的周期全仓审查 run code-review-1791565480（868 轮、828 次工具调用、名义成本约 69.6 美元），error 收场抢救落账仅保住 92 条发现，90 条 open 条目滞留台账。两个系统性缺口：

1. 周期审查车道派发无夜间窗避让。`_run_code_review_checkpoint`（core/admin_monitor.py:1533）守卫链只有 enabled→run_at→同日防重→单飞→manifest 非空，`_night_dispatch_block_reasons`（admin_monitor.py:5421）只挂在派发重试（:4390）与 Administrator 唤起（:5624）两处；该车道 01:00 起跑（.fenix/config.yaml:304）、实测约 2 小时，落点必然压在 03:00-04:45 的任一断窗上。
2. 抢救落账后无 partial 痕、全仓快照核销对 scheduled 车道永不发生。error 收场抢救（core/agent_runner/maintenance_runs.py:1839）只 upsert 且红线禁核销（正确），但成功路径核销资格门是 `run_ok and review_kind == "manual_full"`（maintenance_runs.py:1721），而周期审查恒传 `review_kind="scheduled"`（admin_monitor.py:1660）——实证近四轮成功完成行 resolved 全为 0（fenixd.log 行 3046/7744/10513/14378）。过期 open 条目因此只能等人工 manual_full 或 fix 车道逐条命中，会被后续 fix 批次重复消费。

离窗抖动并非单点：kern.log 保留期内 04:30 窗外已现 6 次（10-02 18:45、10-03 03:00、10-03 06:29、10-06 20:25、10-10 03:00、10-10 04:39），单窗模型对这类形态无覆盖。

# What Changes

1. 窗模型多窗化：`_parse_night_quiet_window` 升级为支持多窗列表（如 `"03:00-03:15,04:15-04:45"`），单窗输入行为不变、空串/off 禁用语义不变；code-fix 守卫与 admin 避让全部消费点改读列表、命中任一窗即避让。
2. 周期审查跨窗顺延：`_run_code_review_checkpoint` 派发前新增「预计跨窗」判定——派发时刻加近几轮 code-review run 实测时长（读归档 run_metrics duration_s 均值，对齐 code-fix 的样本策略）得预计结束区间，与任一静默窗相交则本轮不派发、不写同日防重状态，留待窗末后巡检自然触发（reason=night_quiet_window_deferred）。
3. salvage partial 痕与 scheduled 全仓核销：error 收场抢救 inserted>0 时写 pending-writeoff 锚文件；核销资格从「仅 manual_full」放宽为「manual_full 或 scheduled 且全仓收集（window_start=None）」，解锁仍由既有 `_writeoff_coverage_guard` + `cumulative_covered_files` 把关（部分覆盖一律维持抢救红线不核销）；pending 锚在核销执行或覆盖完整成功收尾时清除。

# Out of Scope

- 不改 error 收场抢救的两条既有红线（部分覆盖下仍绝不核销、绝不激活 code-fix）。
- 不改熔断/冷却/unseal 语义（fix-provider-transient-backoff、evo-fix-transient-break-unseal-backoff 现状保留）。
- 不做抖动探测式动态窗（多窗配置已覆盖观测到的离窗形态；探测留待观测积累后另立）。
- 不动 spec-review / regression / 自省车道的派发时点。
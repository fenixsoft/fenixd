# 调度重试计数记账
<!-- knowledge: capability=dispatch-retry-accounting rev=1
     sources=spec/changes/evo-unfreeze-retry-counter-reset -->

调度重试计数（`_retry_count`）是 SPEC 派发失败预算的单一账本：连续失败递增、达上限冻结转人工、解冻与管理复位清零、冻结陈述如实呈现；done 态推送的人工重推计入同一记账纪律。

## 规则

- 计数与封顶：`_retry_count` 按 SPEC 记账，full 与 fast-track 两车道共用同一计数器；派发失败出口在锁内原子递增（`bump_counters` 消费写后值参与阈值判定，防并发写回丢增量），达到有效上限即 `freeze_for_human` 冻结转人工、不再自动重派。判定口径为「先递增后比较、`>=` 封顶」——恰好允许上限次数的自动重试；上限取 `agents.max_retries` 三车道单一读取器归一（非法值回退缺省 3；0 = 不自动重试是合法语义，无下限钳制）。记账 IO 失败不放大处置：递增未落盘时按读取侧旧值 +1 内存继续参与阈值判定与文案。
- 成功收口清零：实现合并成功等收口路径以绝对写清零 `_retry_count`（重置语义）；计数只反映连续失败，成功收口一次即归零重算。
- 清零集覆盖纪律：人工解冻（`unfreeze_spec` 清零集）与 dashboard 管理复位（`_RETRY_COUNTER_RESETS`）的计数清零集 MUST 覆盖 `_retry_count`（置 0）——解冻/复位即给 SPEC 完整的新重试预算，解冻后首轮失败计数从 1 起算（0+1 ≤ 上限，不触发冻结）。清零集漏键会使残留旧计数在解冻后首轮失败即按 N+1 ≥ 上限的越限形态立即再冻结，人工放行出口形同虚设；新增生命周期计数器并入清零集时同此纪律。
- 冻结陈述取真实计数：冻结转人工 error 文案中的已试次数 MUST 取真实计数器值（单一落点 `freeze_counter_note`，形如「3/3 轮」，两车道五处冻结文案共用），MUST NOT 硬编码为上限值；越限形态（计数 > 上限）如实显示并在保留上限值展示的前提下注明「已越限」，且与同事件 ERROR 日志的计数口径一致。
- 人工重推记账显式：done 态推送的人工重推与自动重试共用同一 push 重试计数器，`approve_push` 以 `source` 标注区分归属（auto=自动链 / manual=dashboard 人工审批信号链）；计数达上限升级 push_failed 信号时，信号 detail 与 error 文案的 `[push_source=…]` 标记如实标注来源。人工重推放行不设 push 计数上限门（保持人工收敛自由度），自动重试的上限与退避语义不变。
- 达上限信号去重：push 重试计数达上限后，同 SPEC 的重复 push_failed 信号在发射点去重——同 SPEC 存在未决同型信号即跳过发射，不重复触发 daemon_errors 升级链；计数仍如实递增并标注来源。

## 代码锚点

- 主实现：`core/pm_engine/dispatch/queue.py`（`freeze_counter_note` 冻结计数文案单点；通用失败/契约违反出口的 bump 与 `retries >= max_r` 封顶冻结）、`core/pm_engine/dispatch/fast_track.py`（fast-track 三处同型 bump/封顶/成功清零）、`core/state_machine.py`（`bump_counters` 锁内原子递增、`unfreeze_spec` 清零集、合并成功收口清零）
- 复位面：`core/dashboard/data/admin_actions.py` `_RETRY_COUNTER_RESETS`
- 推送面：`core/pm_engine/engine.py` `approve_push`（source 透传）、`_handle_push_failure`（来源标注记账）、`_signal_push_failed`（同 SPEC 未决同型信号去重）
- 守卫测试：`tests/test_unfreeze_retry_counter_reset.py`（解冻清零/复位键集合/越限文案/重推去重四场景）

## 溯源

- 2026-11-17 evo-unfreeze-retry-counter-reset（spec/changes/evo-unfreeze-retry-counter-reset/） — 新增本能力：解冻与管理复位清零集补 `_retry_count`、冻结文案已试次数取真实计数（五处收敛 `freeze_counter_note` 单点、越限注明「已越限」）、人工重推 source 记账与 push_failed 同 SPEC 未决信号去重

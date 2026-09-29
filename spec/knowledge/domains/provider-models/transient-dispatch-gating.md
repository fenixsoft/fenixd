<!-- knowledge: capability=transient-dispatch-gating rev=2 sources=spec/archive/2026-09-13-fix-provider-transient-backoff,spec/archive/2026-09-29-evo-fix-transient-break-unseal-backoff -->

# 瞬断终态排程重派与全局熔断

dispatch 层对瞬断终态失败的延迟重派，以及同错误指纹风暴触发的全局派发冻结。

## 规则

- dispatch 层处理 implementer / fast-track / repair 的失败收场时，错误带 `[provider-transient]` 标记的 run 跳过「`_retry_count` 递增/清零 + 立即重新入队」路径，改按 `agents.transient_redispatch_delay_seconds`（缺省 600）排程恢复定时器，到期重新进入派发流程；重派经 worktree 复用通道认领前一轮现场（见 [provider-transient-backoff](provider-transient-backoff.md)）。
- 死亡 run 的预算豁免行为保持不变；错误不带 `[provider-transient]` 标记的终态走现行重试计数/清零/重入队路径，行为不变。
- 全局同错误指纹熔断：错误文本经归一化（剥离 model 名等可变字段）生成指纹，在 `agents.transient_break_window_seconds`（缺省 600）滑动窗口内同一指纹出现次数达 `agents.transient_break_threshold`（缺省 3）时触发熔断——冻结全部新 run 派发 `agents.transient_break_cooldown_seconds`（缺省 600），并发出带 15 分钟节流的 major 告警；在飞 run 不受影响。
- 指纹计数与熔断状态保存在进程内存（与既有 4xx 熔断同构），daemon 重启清零；冷却到期解封时窗口内指纹计数清零重新起算，派发恢复经解封渐进恢复节奏（hold→单条探针→错峰放行）分批放行，不同拍全量放出（见 [transient-unseal-recovery](transient-unseal-recovery.md)）。
- 熔断触发条件、滑动窗口、冻结期时长与指纹归一口径独立于解封节奏，解封节奏不回改这些语义。
- 熔断触发时的失败 attempt 聚合上下文与自然过期自动核销见 [provider-circuit-observability](provider-circuit-observability.md)；治理配置项的设置界面见 [transient-controls-ui](transient-controls-ui.md)。

## 溯源

- [2026-09-13 fix-provider-transient-backoff](spec/archive/2026-09-13-fix-provider-transient-backoff/) — 建立 [provider-transient] 终态延迟重派（替代立即重入队）、归一化指纹全局熔断与进程内存计数语义
- [2026-09-29 evo-fix-transient-break-unseal-backoff](spec/archive/2026-09-29-evo-fix-transient-break-unseal-backoff/) — 解封出口改为渐进恢复节奏（hold→探针→错峰，解封细节拆分至 transient-unseal-recovery 能力页），熔断触发/滑窗/冻结期与指纹归一口径不变

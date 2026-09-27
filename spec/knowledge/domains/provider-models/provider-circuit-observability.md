<!-- knowledge: capability=provider-circuit-observability rev=1 sources=spec/archive/2026-09-24-evo-transient-storm-alert-context -->

# 瞬断风暴告警上下文与自动核销

全局瞬断熔断的可观测配套：告警携带风暴内失败 attempt 聚合清单，熔断自然过期后自动核销告警。

## 规则

- 触发全局瞬断熔断（transient 达阈值，见 [transient-dispatch-gating](transient-dispatch-gating.md)）时，告警上下文（ERROR 日志 + transient_break_storm 升级信号）必须附窗口内失败 attempt 的聚合清单（run_id / spec / 时间戳 / provider），与归一化指纹并列，可据此定位风暴来源模型/provider 与波及 run。
- 全局熔断自然过期时自动核销对应 transient_break_storm 告警：标记 handled=True、handled_by="auto-resolve"、核销原因「熔断自然过期」落审计，经既有 AdminStore.auto_resolve 通道执行。
- 过期判定口径：派发闸门查询首次观察到 `now >= 熔断到期时点` 的时点即为熔断自然过期。
- 核销候选必须显式取「窗口内最新的未处理」告警：候选获取通道（AdminStore.latest_signal）不做 handled 过滤，实现须在候选上显式判定 `handled is not True`，否则核销静默失效；窗口内更新的已处理条目不得抢占候选。
- 幂等：无对应告警或候选均已核销时零操作零写回——不创建新记录、不改写已 handled 条目的任何字段。
- 复用既有告警生命周期通道（alert admin store），不引入新告警 kind；核销动作为审计记录而非关闭信号。

## 溯源

- 2026-09-24 evo-transient-storm-alert-context — 补齐风暴告警的失败 attempt 聚合上下文，并建立熔断自然过期的自动核销通道（含未处理候选显式判定与幂等语义）

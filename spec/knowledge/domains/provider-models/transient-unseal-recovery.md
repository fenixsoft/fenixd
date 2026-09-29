<!-- knowledge: capability=transient-unseal-recovery rev=1 sources=spec/archive/2026-09-29-evo-fix-transient-break-unseal-backoff -->

# 瞬断熔断解封渐进恢复

全局瞬断熔断冷却到期后的恢复节奏控制：解封不立即放行，经 hold→单条探针→错峰放行三段把积压摊开，防止积压在解封瞬间同批重撞刚恢复的 provider。

## 规则

- 熔断冷却到期解封后 MUST NOT 立即一次性放行全部积压：先进入 post-unseal hold，时长为 hold 基数 × 解封后的当前解封次数（首场解封 hold=基数而非 0），多指纹并存时取各指纹次数最大值，封顶 600 秒；hold 期内派发闸门整队持有。
- 解封次数按归一化指纹记忆，保存在进程内存，daemon 重启清零；稳定观察窗（缺省 30 分钟）内无新熔断时按整窗衰减减一、衰减至 0 为止（非到期一次性清零），衰减复位后下一场解封 hold 回到基数水平。
- hold 期满进入探针观察窗（缺省 120 秒），期间仅放行恰好一条最高优先级派发作为探针，其余积压继续持有；观察窗内非同指纹的新记账不判探针失败。
- 探针判败依据为观察窗内出现同指纹新瞬断记账（复用既有指纹滑窗，不引入新的探测调用）；观察窗期满无同指纹新记账即判探针通过。
- 探针通过后其余积压按既有队列优先级（priority+aging）错峰放行：按错峰节拍（缺省 30 秒）每拍准入一条，MUST NOT 同拍全量放出；积压放完（队列空回调）或到达放行硬过期（max(观察窗×10, 600 秒)）即退出错峰态恢复常态派发节奏。
- 探针失败时按现行熔断规则重新冻结全部新派发（冷却与触发路径同配置源），该指纹解封次数额外 +1（下一场 hold 相应加长）；告警链路照常，不新增告警种类。
- 派发首道闸按态序短路消费：冻结 > post-unseal hold > 探针观察窗 > 错峰放行 > open（短路顺序即优先级）；hold/观察窗期内失败再触发熔断时 hold 与探针态作废、按冻结语义重计。
- 解封节奏单条准入在队列 pop 前消费；pop 后闸门回滚条目（本轮零 run 启动）时按消费时闸态对称退还——探针名额复位、错峰节拍锚点回拨至当前时刻，防止名额或节拍被未启动的条目空烧。
- hold 期满、观察窗期满、错峰节拍到期 MUST 经单飞行定时器链主动唤醒派发通道，MUST NOT 依赖外部触发点才被发现；熔断到期唤醒与告警自动核销照旧在解封时先行执行。
- 闸门判定、准入与退还全部 fail-open：runner 不可用或判定异常时按 open/放行处理，解封节奏机制故障不放大为调度故障。
- 配置五键 `agents.transient_unseal_*`（经 core/config.py 规范化，缺省启用、数值保守）：`transient_unseal_backoff_base_seconds`=60（hold 基数）、`transient_unseal_backoff_max_seconds`=600（hold 封顶）、`transient_unseal_probe_window_seconds`=120（探针观察窗）、`transient_unseal_stable_window_seconds`=1800（稳定衰减窗）、`transient_unseal_release_stagger_seconds`=30（错峰节拍）；base 与 stagger 取 0 语义为禁用（base=0 回到「到期即全量放行」且不记忆解封次数，stagger=0 错峰不节拍）；数值非法回退缺省、显式 0 保留；每次读取即取当前配置，30 秒热更新即时生效；五键未纳入设置页「瞬断治理」分组与受管配置键白名单，仅经配置文件生效。
- 既有三层退避语义不变：attempt 原地退避（见 [provider-transient-backoff](provider-transient-backoff.md)）、per-spec 重派延迟与熔断冻结期（见 [transient-dispatch-gating](transient-dispatch-gating.md)）；不做派发前主动 LLM 健康探测。

## 溯源

- [2026-09-29 evo-fix-transient-break-unseal-backoff](spec/archive/2026-09-29-evo-fix-transient-break-unseal-backoff/) — 新建：解封次数记忆 + post-unseal hold + 单条探针 + 错峰放行状态机与配置五键；既有测试的「到期即清零重计」语义保留、「解封立即全量唤醒」改写为 hold+探针

# 能力：lane-preflight（车道前置探针稳态观测）

## 需求

### R1 稳态边沿发射
- 探针周期判定「同判」时 MUST NOT 逐拍重复发射同文 WARNING 日志；「同判」指 `(ok, fallback_verdicts, reasons 归一集)` 三元全同，任一漂移（含 unhealthy 同判但失败形态变化）按结论变化处理。判定结论变化（含进程启动首判）必须即时发射。
- 稳态期间以每小时至多 1 条的心跳维持可观测性，心跳携带稳态持续时长。
- 稳态记忆 MUST 进程级单例并锁保护，持续时长以 monotonic 时基计。

### R2 不可判定为显式稳态
- 「部署形态不可判定」（进程无 provider 路由环境变量、CLI 默认档）按显式稳态处理：判定结论与回落冻结闸拦截语义保持现状，仅观测面（日志/告警）按稳态降噪。
- 不可判定结论可被 evo-repair-lane-credential-probe-fix 1.2 的试呼裁决翻转，翻转按结论变化（新边沿）处理。

### R3 双发射点一致
- agent_runner 探针体与 daemon 自检消费点共享同一稳态判定，同一判定拍至多一条 WARNING 日志。

### R4 告警生命周期对齐
- 结构性稳态告警在人工处置（handled）后，同一稳态持续期间 MUST NOT 被任何告警登记调用方重开（闸收口在 ensure_lane_env_alert 入口，覆盖 fenixd.py _lane_preflight_consume 的 startup/periodic 与 core/pm_engine/arbiter.py run infra 失败路径）；判定改变时按新边沿重新登记并即时告警。
- 稳态不重开闸 MUST NOT 拦截 AdminStore update 定位改写路径（evo-repair-lane-credential-probe-fix 1.3 的 >24h 话术翻转依赖该路径）。
- 告警正文承诺的生命周期语义（如「随恢复自动关闭」「无需人工处置」）必须与其实际关闭/重开行为一致。

### R5 与 evo-repair-lane-credential-probe-fix 的范围切分
- 本能力 MUST NOT 修改 core/self_review.py 提醒面：「超 24h 未处理」提醒的生命周期方向（含豁免/升级话术翻转）由 evo-repair-lane-credential-probe-fix 1.3 单源裁决，两 SPEC MUST NOT 对同一告警面发出相反指令。

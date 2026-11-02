# Why

网卡断连已从「每日 04:30 单窗」升级为散布多时点：内核日志可核窗口内 8 次 enp42s0 Link is Down（10-16 20:30:24，10-17 03:00:01、03:01:21、04:30:02、04:31:21、16:14:25、17:09:13、19:46:27），10-17 凌晨两波一夜击杀三个在飞 run（自进化 11.91 美元沉没＋秒死 run 告警噪音＋周期审查 136.20 美元撞窗，合计约 148 美元）。守卫面三个残余缺口：①多窗解析已上线（core/code_fix.py:3381）但缺省仍单窗 04:15-04:45（core/code_fix.py:3346）且配置面从未启用，03:00 形态零覆盖；②自进化车道派发链（fenixd.py:4843 检查点 → core/agent_runner/maintenance_runs.py:1353 → runner.py:5985 _run_agent，Popen 单点 :6138）全程无任何窗判定，evo-1792174603 02:16 出发即无从避让；③派发路径无连通预检（全核仅 provider_circuit.py:124-138 事后 ENOTFOUND 分类，模式行 :138），断连活跃期照常派发产生秒死与告警噪音（evo-1792177308，03:01:48 派发、114 秒死）。

# What Changes

1. 缺省窗多窗化：NIGHT_QUIET_WINDOW_DEFAULT 改为「03:00-03:15,04:15-04:45」（解析器零改动），全部消费点（code-fix 批守卫、周期审查顺延、admin 唤起避让）经同一解析器自动生效；同步 config.template.yaml 文档化该键与多窗示例；运行时 config 显式覆盖与空串/off 禁用语义不变。
2. 自进化车道窗避让：_check_evolution_checkpoint（fenixd.py:4843）派发前做预计跨窗判定（复用 _parse_night_quiet_windows，配置读同键 admin.code_review_fix.night_quiet_window、缺省 NIGHT_QUIET_WINDOW_DEFAULT；时长估计取近几轮自进化归档 run_metrics duration_s），命中即本轮跳过（reason=night_quiet_window_deferred 日志）、留待窗后巡检，不消费水位/就绪标记。
3. 派发前连通预检：core/agent_runner/runner.py:5985 _run_agent（全车道共用 Popen 单点 :6138）派发前做一次轻量 DNS 探测（getaddrinfo API 域名、秒级超时），按 agent_type 白名单仅作用于维护车道派发（dispatch 族 spec/impl/dispute-judge/spec-review、regression 与交互式 run 不做探测顺延，见 Out of Scope），失败则顺延本轮派发并记跳过日志；探测自身异常一律放行（fail-open），顺延由各车道既有重触发节奏自然接续。

# Out of Scope

- 不改守卫命中后的冷却/熔断/salvage 语义（provider_circuit 事后熔断保持现状，与本预检正交）。
- 不做抖动探测式动态窗（沿 evo-add-review-night-defer-snapshot-writeoff 的既定边界，留待观测积累另立）。
- 不动 spec-review / regression 车道派发时点。
- 不改运行时 .fenix/config.yaml（git 不跟踪，部署侧可显式覆盖缺省，不入 SPEC 交付）。
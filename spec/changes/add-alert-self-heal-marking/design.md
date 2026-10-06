## Context

`core/alert_lifecycle.py` 为纯函数评估器（输入告警列表＋spec 状态表 → 输出可闭环条目），写回由 `AdminStore.auto_resolve` 在排他锁内完成（`handled_by="auto-resolve"`，仅 `kind=escalation`）。条件枚举 `_SIGNAL_CONDITIONS` 仅四族 spec 附着信号；`evaluate_alert` 对 `spec` 为空的条目直接返回 None（「无 spec 字段：无法关联」）——daemon_errors、run_infra_failure、evo 分析失败、处置收敛升级四族全部 spec-less，故永不闭环。告警条目已携带 `last_seen`（signal 族，复现时刷新）与 `created`（各族），安静证据无需读日志。写入侧已有统一埋点 `attach_trigger`（pm_engine / admin_monitor 各写入点复用），未列类型返回 None 不写 trigger。

四族写入点：daemon_errors 升级与收敛 escalation（`core/admin_monitor.py`）、run_infra_failure 熔断告警（`core/admin_monitor.py`，文案见 `:455` 处置映射）、evo 分析 run 失败（仓库交付源 `fenixd.py` 的 `_evolution_warn`，`.fenix/fenixd.py:4433` 为部署副本）。

## Goals / Non-Goals

- Goals：自愈型瞬态告警安静超窗后自动标「已自愈」转已处理；存量积压回填；收口可辨识（徽标＋note 证据）；不破 fail-closed 处置契约。
- Non-Goals：不改既有四族 spec 附着条件的判定；不改 AdminMonitor 孤儿处置收敛核查本身（其升级产物可被自愈收口，但核查逻辑与 disposition 台账不动）；不动 env 豁免握手族；不做告警预测/聚合。

## Decisions

### D1 安静证据取条目自身时间戳，不读日志

signal 族条目复现时刷新 `last_seen`（既有行为，实证：9-29 条目 last_seen 晚于 created）；escalation/disposition 族回落 `created`；收敛升级取双源锚点（`admin_run_id` 名下 disposition ＋ 同 signal_type 未收口 signal——signal 记录不携带 `admin_run_id`，关联规则见 D2）。判定输入全部调用方注入（`now`＋告警列表），模块保持纯函数——**不读 fenixd.log**（日志轮转会让证据不稳定，条目时间戳由框架写入链维护，口径单一）。

### D2 覆盖族注册表＋保守缺省

`SELF_HEAL_SIGNAL_TYPES` 注册表初始成员：daemon_errors、run_infra_failure、`self-evolution`（evo 分析 run 失败，写入点 `fenixd.py` `_evolution_warn` 实际常量）。spec-less escalation 按两种形态判定，MUST 都覆盖：

- **收敛升级**（`kind=escalation`＋`spec` 空＋`admin_run_id` 存在，如「处置终态未收口」）：signal_type 复制底层 sig_type；安静锚点取「`admin_run_id` 名下 disposition 条目（处置记录不带 last_seen，回落 created）」与「同 signal_type 的未收口 signal 条目」两者的最新复现时刻。signal 记录不携带 `admin_run_id`（merge_signal 仅按 (spec, signal_type, status_hash) 沉淀；admin_run_id 只出现在 escalation/disposition 写入链），按 signal_type＋spec 空匹配——MUST NOT 只锚 disposition created，否则底层风暴仍在复现（signal 条目 last_seen 持续刷新）时 escalation 会被提前收口，违背 D4 的复发节律覆盖。
- **裸升级**（`kind=escalation`＋`spec` 空＋signal_type ∈ 注册表＋无 `admin_run_id`，即 evo 族）：按条目自身 `last_seen` 判定——merge 不作用于 escalation（`AdminStore.merge_signal` 明示 escalation/disposition 永不参与合并），实际回落 created。

未注册类型、形态不符一律不闭环——「未识别永不自动闭环」契约原样保留。

### D3 写回独立标识，双 kind 支持

新增 `AdminStore.auto_self_heal`（并列既有 `auto_resolve`，不复用不改其签名语义）：可关闭 `kind ∈ {escalation, signal}`，`handled_by="auto-self-heal"`，note 前缀「已自愈：」＋证据（安静时长、最近复现时刻）；`handled=True` 跳过；排他锁单次读-改-写；零写回 mtime 不变。**MUST NOT 触碰 disposition 记录**（result/status 逐位不变）——自愈收口的是人工甄别面，不是处置台账；AdminMonitor fail-closed「不补记 resolved」语义完整。

### D4 窗口默认 1440 分钟（盖过跨日同刻复发节律）

实证指纹 822c197a 以 ≈24h 间隔复发一次；1440 分钟窗口保证「最后一次复发后一整个复发周期无复现」才收口，避免收口后立即重开。可配 `admin.self_heal_quiet_minutes`（`get_admin_config` 段兜底，非正 int/类型错误回退 1440，对齐既有脏值回退口径）。复发后新条目由既有冷却/去重自然产生，不重开旧条目。

### D5 存量回填对齐既有 D4 模式

无 trigger 的 spec-less 条目按 `signal_type ∈ SELF_HEAL_SIGNAL_TYPES` 推断参与判定（现有 `BACKFILL_SIGNAL_TYPES` 机制并列扩展，note 注明存量回填）。当前积压（含两条滞留「处置终态未收口」）安静超窗后自动转已处理。

### D6 Dashboard 呈现：「已自愈」徽标＋已处理视图自然收纳

`core/dashboard/data/admin_alerts.py` 透出 `handled_by`；`alert-shared.tsx` 徽标映射 `auto-self-heal → 已自愈`（区别于既有 `auto-resolve` 徽标文案）；待处理队列天然排除 handled 条目（既有过滤），无需新逻辑。设置页 `SystemPanel.tsx` 增安静窗口分钟数字段（`config_admin.py` 读写校验）。

## Risks / Trade-offs

- ［中→低］误收口风险：某故障以 >24h 周期复发会被提前收口——由「复发即新条目＋冷却节流」兜底，代价仅是重新出现一条告警，可接受；窗口可调大。
- ［低］收敛 escalation 收口后，若用户从未看过处置结论——note 附底层 run_id 与安静证据，已处理视图可追溯。
- ［低］`kind=signal` 纳入写回范围是 `auto_resolve` 既有约束（仅 escalation）的扩张，独立函数承载不混淆既有语义；测试显式覆盖 signal 族写回。

## Migration Plan

纯增量：新条件族/新写回路径/新配置键，存量数据零迁移（无 trigger 条目走回填推断）。上线后首批收口发生在积压条目安静满窗后的下一轮巡检。

## Open Questions

（无——窗口默认值按「跨日复发节律」证据定为 1440 分钟，可配可调。）

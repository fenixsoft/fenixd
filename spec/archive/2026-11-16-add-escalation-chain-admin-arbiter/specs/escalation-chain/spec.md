# escalation-chain Spec

## ADDED Requirements

### Requirement: 处置链路由

升级边信号（`freeze_for_human` 全族与 `_send_human_escalation_alert` 全部调用点）SHALL 默认进入处置链，链序固定：**Admin（受限环境运维）→ Arbiter（全局拍板）→ 人工**。链内任一级处置成功即闭环，人工队列零痕迹；仅链终点（Arbiter 失败）产生人工告警。各信号既有自愈/重试梯子（transient backoff、verify 重验、severity 批闸、同因重派熔断）MUST 原样保留——本能力只改梯子耗尽那一刻的去向。

链入口 SHALL 按信号来源判定防自环：只收框架/runner 侧产生的信号；链成员的处置输出永远是链内转单边（Admin 超范围→Arbiter、处置失败→下一级），MUST NOT 作为新信号重新入链。`admin_dispatch_programming_error` 等框架自指类照常入链头。

#### Scenario: 升级信号入链头 Admin 接单

- **WHEN** 某升级边信号触发（如 `inconclusive_loop`）且链可用
- **THEN** 信号派发 Admin 处置（链单飞队列），人工队列无新条目、无推送

#### Scenario: Admin 修复成功闭环

- **WHEN** Admin 处置 run 终态 resolved（如修复验证夹具并重置重验）
- **THEN** 信号闭环（处置收口 + spec 状态恢复可运行），全程人工队列无条目

#### Scenario: 链成员输出不自环

- **WHEN** Admin 处置产出「超范围」转单（`handoff: arbiter`）
- **THEN** 该件直达 Arbiter 单飞队列，不重入链头、不计 Admin 失败

#### Scenario: 框架自指类照常入链

- **WHEN** `admin_dispatch_programming_error` 信号触发
- **THEN** 正常进入链头派发（Arbiter 具备立项修框架通道，修不动即上升人工）

### Requirement: Admin 车道链上语义

Admin SHALL 作为链第一级以既有受限形态处置（受限工具、只见当前 run 注入结果）：

- 尝试配额 2 次/签名（run 崩溃/超时计一次；自判超范围转单不计失败）
- 超范围转单为结构化产出 `handoff: arbiter` + `handoff_reason`（新增字段，MUST NOT 重载 `result=escalate` 现语义）；Administrator prompt 契约段同步
- 处置成功的终态收口 MUST 同时完成信号收口与 spec 状态恢复可运行（框架侧 side-effects，显式 status 解冻、拒绝 parse 兜底——与 Arbiter `_apply_disposition_side_effects` 同型纪律）

#### Scenario: Admin 烧满配额转 Arbiter

- **WHEN** 同一签名 Admin 处置连续 2 次 run 失败
- **THEN** 该件转单 Arbiter（附 Admin 尝试痕：run 摘要与失败原因），不再派 Admin

#### Scenario: Admin 超范围转单不计失败

- **WHEN** Admin 处置产出 `handoff: arbiter`（如预算类信号超出环境运维面）
- **THEN** 该件立即转 Arbiter，Admin 配额计数不变

#### Scenario: Admin 处置成功解冻 spec

- **WHEN** Admin 修复了导致 `verify_env_blocked` 冻结的环境问题并落 resolved 终态
- **THEN** 框架侧 side-effects 以显式 status 解冻该 spec 并触发重验证（无「告警闭环但 spec 永久 frozen」残留）

### Requirement: Arbiter 拍板与复现配额

Arbiter SHALL 作为链第二级以全局视野接单（转单载荷含 Admin 尝试痕），并获得预算豁免拍板动作面：可写 spec 预算 override 字段（`impl_run_budget_override` 等）并落台账留痕。复现配额：同签名拍板 2 次后问题第 3 次复现 MUST 上升人工。既有「同签名只自主处置一次」纪律（`_dispositioned`/`_ledger_sigs` 永久跳过）由配额制取代，回扫排除逻辑与机械守卫测试同步改写；例外：dead-man/停机类基础设施死亡签名维持永久单次、不适用复位。

配额复位：签名连续 7 天无复现清零，或该 spec 状态发生迁移清零。签名遵循「同一个问题」语义：spec=null 信号签名 SHALL 含主体键（从信号 payload 提取，如蒸馏欠账归档名、triage 场景集指纹），提取不到时退化为类型级并在台账标注粒度。

#### Scenario: 预算信号 Arbiter 拍板豁免

- **WHEN** `impl_budget_exhausted` 触发且 Admin 已超范围转单
- **THEN** Arbiter 拍板落预算豁免（override 字段+台账留痕），spec 恢复调度，人工零感知

#### Scenario: 复现第 3 次上升人工

- **WHEN** 同一签名 Arbiter 已拍板 2 次、问题第 3 次复现
- **THEN** 强制上升人工，告警附 Admin 尝试痕 + Arbiter 台账五段 + choices

#### Scenario: 配额复位

- **WHEN** 某签名连续 7 天无复现（或其 spec 状态迁移）后同签名再次触发
- **THEN** 配额从 0 重新计数（Arbiter 可再次自主拍板）

#### Scenario: dead-man 例外不复位

- **WHEN** dead-man/停机类签名曾经处置、7 天后同签名再次触发
- **THEN** 不再自主处置，直接上升人工（永久单次语义保留）

### Requirement: 失败双轨上升

链终点上升 SHALL 由两轨触发：(a) Arbiter 自判无法处理/无法决策/尝试无效（含 run 崩溃超时，沿用同签名失败重试 1/2 次与半成品调查包机制）；(b) 复现配额（2 次拍板后第 3 次复现）。上升件 MUST 附全链痕迹（Admin 尝试痕、Arbiter 台账五段、剩余 choices）与全链关联键（链 run_id 族），链上任一级后续成功闭环时自动收口上升件（`close_cause` 族标记）。

#### Scenario: Arbiter 自判失败上升

- **WHEN** Arbiter 调查后明确「无法处理」（run 正常终态但结论为须人工）
- **THEN** 上升件落人工队列（附调查台账与 choices），链终结

#### Scenario: Arbiter run 崩溃重试后上升

- **WHEN** Arbiter run 崩溃、同签名重试 1/2 次仍失败
- **THEN** 半成品调查包随上升件落人工队列

#### Scenario: 上升件随链成功自动收口

- **WHEN** 上升件在人工队列期间，同签名问题被后续链轮次（如人工未动作而环境自愈后链重验成功）闭环
- **THEN** 上升件自动标记 handled（附 close_cause），不滞留

### Requirement: 黑名单 kill switch 与降级

触发面 SHALL 配置化为黑名单（初始空集）：黑名单内信号绕过全链直达人工队列（写入即按降级态降噪分级标记 handled 的既有语义保留）。`arbiter.enabled=false` 或 Admin+Arbiter 车道双双失能（如 harness 级 spawn 失败被链级判定）时，整体退回现状行为：升级边直达人工队列（critical/major 进 pending、warning/minor 写入即 handled 的既有降噪生效）+ narrative 补叙。降级态行为 MUST 与本 SPEC 合入前逐字节一致；恢复入链时无需人工干预。

#### Scenario: 黑名单信号直达人工

- **WHEN** 运维热加某信号名进黑名单后该信号触发
- **THEN** 不派发 Admin/Arbiter，告警直接落人工队列

#### Scenario: 关闭态零侵扰

- **WHEN** `arbiter.enabled: false`
- **THEN** 全部告警路径与合入前逐字节一致（含降噪分级与 narrative 补叙）

#### Scenario: 链级失能 fail-open

- **WHEN** 链级判定 Admin/Arbiter 车道 spawn 失能（配置问题，非单件失败）
- **THEN** 升级边直达人工（不逐件烧配额），一次性 WARN 留痕；配置修复后自动恢复入链

### Requirement: 存量迁移

框架 SHALL 在启用链路由的首个 daemon 启动执行一次性迁移：存量 pending escalation 中能判定「底层已闭环」（同签名 spec 已终态或处置已 resolved）的自动收口（附 `close_cause=migrated`），其余保留人工队列；MUST NOT 回填入链。

#### Scenario: 已解决存量自动收口

- **WHEN** 迁移运行时存在底层 spec 已 done 的 pending escalation
- **THEN** 该条目被标记 handled（close_cause=migrated），人工队列不再显示

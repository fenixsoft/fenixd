## ADDED Requirements

### Requirement: 基础设施瞬态告警自愈闭环

- 覆盖族注册表 `SELF_HEAL_SIGNAL_TYPES` 初始 MUST 含 `daemon_errors`、`run_infra_failure`、`self-evolution`（evo 分析 run 失败，写入点仓库交付源 `fenixd.py` `_evolution_warn` 的实际 signal_type 常量）；注册表外 signal_type 永不自愈闭环（保守缺省不变）。
- 自愈判定（签名安静）：条目最近复现时刻取条目自身 `last_seen`，缺失回落 `created`。spec-less escalation 分两形态：收敛升级条目（`kind=escalation` 且 `spec` 为空且带 `admin_run_id`）取「`admin_run_id` 名下 disposition 条目」与「同 signal_type 的未收口 signal 条目」（signal 记录不携带 `admin_run_id`，按 signal_type 匹配）两者的最新 `last_seen`/`created`；裸升级条目（`kind=escalation`、`spec` 为空、signal_type ∈ 注册表且无 `admin_run_id`，如 evo 分析失败 `self-evolution`）按条目自身 `last_seen`（缺失回落 `created`）判定。判定满足：`now − 最近复现时刻 ≥ admin.self_heal_quiet_minutes`（默认 1440）。
- 判定输入（告警列表、当前时刻）MUST 全部由调用方注入；`alert_lifecycle` 模块 MUST 保持纯函数，不读写文件、不依赖锁（既有架构约束）。
- 写回 MUST 走独立标识 `handled_by="auto-self-heal"`，`resolve_note` MUST 以「已自愈：」前缀并附安静证据（安静时长与最近复现时刻）；MUST NOT 改写 disposition 记录本体（AdminMonitor 生效核查 fail-closed 契约不破）；`handled=True` 条目 MUST NOT 覆盖。
- 收敛升级条目自愈收口后，若底层故障复发，由既有信号冷却/去重机制自然产生新条目，MUST NOT 重开已收口条目。
- 排除项：`inconclusive_loop`（env 豁免握手族）永不自愈闭环；spec 附着族（有 spec 字段且命中既有条件枚举）仍由既有条件判定，MUST NOT 双重判定。

#### Scenario: 安静超窗的 daemon_errors 信号自动自愈

- **WHEN** 某 `kind=signal`、`signal_type=daemon_errors` 的条目 `last_seen` 距今 ≥ 1440 分钟，且同批巡检中对应的收敛 escalation（同签名组）也满足安静判定
- **THEN** 下一轮巡检两者同批写回 `handled=True`、`handled_by=auto-self-heal`、note 前缀「已自愈：」，离开待处理队列进入已处理视图

#### Scenario: 窗口内仍复现则保持待处理

- **WHEN** 条目 `last_seen` 距今 < 1440 分钟（签名仍在复现）
- **THEN** 判定返回不可闭环，条目保持待处理原状

#### Scenario: 收敛升级收口不触碰处置台账

- **WHEN** 收敛升级 escalation 引用的处置组已全部终态且底层签名安静超窗
- **THEN** 仅该 escalation 条目被标已自愈；名下 disposition 记录的 result/status 字段逐位不变

#### Scenario: env 握手族永不自动闭环

- **WHEN** 条目 signal_type 为 inconclusive_loop（env 豁免握手族）无论安静多久
- **THEN** 永不自愈闭环，仍须人工裁决收口

#### Scenario: 人工处理记录不可覆盖

- **WHEN** 条目已被人工 handled=True
- **THEN** 自愈判定跳过，字段逐位不变

#### Scenario: 安静窗口可配且脏值回退

- **WHEN** `admin.self_heal_quiet_minutes` 配置为 720 时生效 720；配置为 -1、"abc"、true 时
- **THEN** 生效 1440，巡检不因脏值中断

#### Scenario: 存量积压回填

- **WHEN** 无 trigger 字段的 spec-less 存量条目 signal_type ∈ 覆盖族，安静已超窗
- **THEN** 按回填推断参与自愈判定并可闭环，note 注明存量回填（对齐既有回填模式）

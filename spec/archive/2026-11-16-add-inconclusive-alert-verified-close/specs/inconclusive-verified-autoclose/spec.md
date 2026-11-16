# inconclusive_loop 告警验证翻绿自动消解

## ADDED Requirements

### Requirement: 验证翻绿自动收口

关联 spec 的状态到达 `verified`、`done` 或 `pushed` 时，该 spec 名下所有未处理（`handled=False`）的 `inconclusive_loop` 告警（kind=escalation 与 kind=signal 皆然）由周期扫描自动收口：`handled=True`、`handled_by="auto-resolve"`，resolve_note 写明「验证已翻绿」依据与状态变更时刻。

- **收口证据**：仅认 STATE.md 状态表的 spec 状态（`verified`/`done`/`pushed` 三态），不解析告警 description、不信任任何 agent 处置自述。
- **双 kind 同治**：escalation（链终点上升件）与携带 trigger 的 kind=signal 条目同走本条件。
- **在途态不收口**：spec 处于 `drafted`/`ready`/`implementing`/`implemented`/`testing`/`blocked` 或状态缺失/不在状态表时，告警保持原状（含人工队列可见性、升级与派发行为均不变）。

#### Scenario: 验证翻绿后升级件自动收口

- **WHEN** 某 spec 存在未处理的 `inconclusive_loop` 升级告警（无 trigger 的存量形态或有 trigger 的在册形态），且该 spec 在 STATE.md 状态表中 status=`verified`
- **THEN** 周期扫描判定该告警可闭环，写回 `handled=True`、`handled_by="auto-resolve"`
- **AND** resolve_note 含 spec 名、「验证已翻绿」表述与状态变更时刻（`updated` 缺失时不硬造时刻）
- **AND** 告警其余字段（description/evidence/escalated 等）逐位保留

#### Scenario: 终态后推同样收口

- **WHEN** 该 spec status=`done` 或 `pushed`（verified 之后推进的终态）
- **THEN** 未处理 `inconclusive_loop` 告警同样按本条件收口

#### Scenario: 离开停车态但未翻绿不收口（回归锚）

- **WHEN** 该 spec status=`testing`（如 auto 重派复位）或 `blocked` 或 `implemented`
- **THEN** `evaluate_alert` 返回 None，告警保持未处理
- **AND** 不得因「已非 blocked」或「已离开停车态」而收口（2026-11-07 add-integration-test-env 16:19 auto 重派反例：离开停车但环境仍坏，收口即假闭环）

#### Scenario: 人工已处理不可覆盖

- **WHEN** 条目 `handled=True`（人工标记或既有处理记录）
- **THEN** 判定跳过，字段与时间戳逐位不变

### Requirement: 存量回填收录

`BACKFILL_SIGNAL_TYPES` 收录 `inconclusive_loop`：无 trigger 字段的存量条目在启动回填轮按**本条件**（`spec_verified`，非宽松终态条件）推断参与判定；无法关联 spec 或条件不满足的保持原状。

#### Scenario: 存量滞留件随回填收口

- **WHEN** daemon 启动首轮存量回填，存在无 trigger、未处理的 `inconclusive_loop` escalation，其 spec status=`pushed`
- **THEN** 按 `spec_verified` 条件收口，resolve_note 带「存量回填」前缀与翻绿依据

#### Scenario: 回填条件与在册映射一致

- **WHEN** 存量 `inconclusive_loop` 条目参与回填判定
- **THEN** 推断条件为 `spec_verified`（状态集三态），不得回退为 `spec_terminal_or_unblocked` 语义（离开 blocked 即收口的宽松口径被 16:19 反例证伪）

### Requirement: 自愈注册表维持排除

`SELF_HEAL_SIGNAL_TYPES` 保持不含 `inconclusive_loop`：安静时长永不构成收口依据；本能力只经 `spec_verified` 条件族通道收口。

#### Scenario: 长时间安静且未翻绿不自愈

- **WHEN** 某 `inconclusive_loop` 告警未处理、其 spec 长期停留非翻绿状态（如 blocked 停车）超过自愈安静窗口
- **THEN** 自愈通道不收口该条目（安静 ≠ 翻绿证据），告警保持人工队列可见

# alert-lifecycle 增量规格

## ADDED Requirements

### Requirement: 告警触发条件结构化记录
系统写入升级类告警时，MUST 在告警条目中附带结构化的触发条件描述（`trigger` 字段），包含可判定闭环的类型标识与关联对象（如 spec 名、计数阈值、报告路径）。触发条件描述 MUST 足以独立判断「该条件当前是否已解除」。

#### Scenario: 升级告警带结构化触发条件
- **WHEN** pm_engine 触发 verify_fail_escalation 告警（spec 验证连续失败 N 轮冻结为 blocked）
- **THEN** 告警条目含 `trigger: {"type": "verify_fail_escalation", "spec": "<name>", "condition": "spec_reach_terminal_or_unblocked"}`
- **AND** admin_alerts.json 中该条目可被后续闭环判定直接消费，无需解析自然语言 description

### Requirement: 条件解除自动闭环
当告警的触发条件解除时，系统 MUST 自动将该告警标记为已解决：`handled: True`、`handled_at` 为解除时刻、`handled_by: "auto-resolve"`、`resolve_note` 记录解除依据（如「spec v2-x 已到达终态 pushed」）。自动闭环 MUST NOT 覆盖已存在的人工处理记录。

#### Scenario: 冻结 spec 到达终态后告警自动闭环
- **GIVEN** spec v2-x 曾触发 verify_fail_escalation 告警（handled=False）
- **WHEN** v2-x 的状态到达终态（pushed/done）或离开 blocked
- **THEN** 该告警在下一轮闭环扫描内被标记 `handled: True, handled_by: "auto-resolve"`
- **AND** `resolve_note` 含 spec 名与终态说明

#### Scenario: 人工处理记录不被覆盖
- **GIVEN** 某告警已被管理员人工处理（handled=True，handled_by 非 auto-resolve）
- **WHEN** 闭环扫描运行
- **THEN** 该告警内容与时间戳保持不变

### Requirement: 闭环扫描时机与成本
闭环扫描 MUST 在既有周期性巡检（daemon 状态扫描）内联执行，不引入独立线程或定时器；单轮扫描 MUST 仅为 O(未闭环告警数)，且未闭环告警为空时零 IO 开销。

#### Scenario: 无待闭环告警时零开销
- **GIVEN** admin_alerts.json 中全部告警已闭环
- **WHEN** 周期扫描执行
- **THEN** 不触发对 admin_alerts.json 的写回（mtime 不变）

### Requirement: 存量告警回填
daemon 启动时（或闭环机制首次生效时）MUST 对既有 handled=False 告警执行一次回填判定：关联 spec 已到达终态或已离开 blocked 的自动闭环（同样带 auto-resolve 标注）；无法关联 spec 或条件无法判定的告警保持原状。

#### Scenario: 历史过时告警被回填闭环
- **GIVEN** admin_alerts.json 存在 2026-08-29 的 6 条 handled=False 升级告警，其关联 spec（v2-config-page、v2-project-list-page）均已 pushed
- **WHEN** 机制上线后首次启动扫描
- **THEN** 6 条告警全部标记 `handled: True, handled_by: "auto-resolve"`，resolve_note 说明回填来源
- **AND** 无法关联 spec 的告警保持 handled=False 不动

### Requirement: 视图告警分组
管理员视图的告警列表 MUST 按处理状态区分展示：待处理（handled=False）默认置顶，已自动解决（handled_by=auto-resolve）与已人工处理（其余 handled=True）折叠或分区展示，默认不与待处理项混排。

#### Scenario: 待处理告警不被历史噪音淹没
- **GIVEN** 视图存在 3 条待处理告警与 20 条已自动解决告警
- **WHEN** 管理员打开告警列表
- **THEN** 默认视图只显著展示 3 条待处理项
- **AND** 已解决区可展开查看（含 resolve_note 与 handled_at）

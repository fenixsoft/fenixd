# alert-lifecycle 规范（修改）

> 修改既有能力 `alert-lifecycle`（spec/archive/2026-09-06-add-alert-auto-resolve、
> 2026-10-25-add-alert-self-heal-marking、2026-10-27-evo-add-signal-subject-terminal-close、
> spec/changes/add-inconclusive-alert-verified-close）。既有 auto-resolve / self-heal-marking /
> terminal-close 语义不变；本变更新增根因标签与 superseded 批量失效终态旁路。

## ADDED Requirements

### Requirement: 告警根因标签

告警 SHALL 携带根因标签（`cause` 字段），由信号产生方在入账时标注（模型链配置、harness CLI 不可达、初始化产物散件、验证契约、daemon 错误等有限封闭枚举）；根因标签与既有 `signal_type`/`severity` 正交——同 `signal_type` 可因归因不同携带不同根因（如派发失败可归因模型链或 CLI）。

#### Scenario: 入账带根因标签

- **WHEN** 任一信号入告警账
- **THEN** 告警记录含 `cause` 字段（封闭枚举值），面板可按根因过滤/分组

### Requirement: 修复生效后同根因批量 supersede

同根因配置修复生效 SHALL 触发该根因未处理告警的批量 supersede：触发判据为「根因对应的修复观测点通过」（如模型链根因 = 校验后加载成功且后续派发成功），满足判据时该根因下全部未处理告警原子批量标记 `superseded`（新终态旁路，不动既有 resolved/acknowledged 语义），记录失效时间与触发观测点；superseded 告警在面板折叠为「已失效」分组（默认收起、可展开查看），不再计入未处理计数与升级链。

#### Scenario: 模型配置修复后旧告警批量失效

- **WHEN** 模型链根因告警在账（如评审连挂/秒挂衍生），随后 config 修复热加载成功且其后首次派发成功
- **THEN** 该根因下全部未处理告警原子标记 superseded（含失效时间与触发观测点记录），面板折叠呈现，未处理计数相应下降，升级链不再引用它们

#### Scenario: 修复未生效不失效

- **WHEN** 热加载成功但其后派发仍失败（观测点未全通过）
- **THEN** 同根因告警保持未处理态，不发生批量 supersede

#### Scenario: 既有终态语义不变

- **WHEN** 告警经既有 auto-resolve / self-heal / 人工 confirmed-close 路径终态化
- **THEN** 行为与引入本能力前一致；supersede 仅作为新增旁路共存，不拦截既有路径
